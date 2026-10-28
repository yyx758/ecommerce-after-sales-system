package com.ecommerce.aftersales.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.dto.AgentGatewayDtos;
import com.ecommerce.aftersales.entity.ChatMessage;
import com.ecommerce.aftersales.entity.ChatSession;
import com.ecommerce.aftersales.mapper.ChatMessageMapper;
import com.ecommerce.aftersales.mapper.ChatContextProjectionMapper;
import com.ecommerce.aftersales.mapper.ChatSessionMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;
import org.springframework.dao.DataAccessException;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/** Builds the short-term Agent context exclusively from Java-owned business data. */
@Service
@RequiredArgsConstructor
public class AgentConversationContextService {

    private static final int CONTEXT_WINDOW_LIMIT = 60;
    private static final int RECENT_MESSAGE_LIMIT = 10;
    private static final int SUMMARY_MAX_CHARS = 1200;
    private static final int USER_GOAL_MAX_CHARS = 300;

    private final ChatSessionMapper chatSessionMapper;
    private final ChatMessageMapper chatMessageMapper;
    private final ChatContextProjectionMapper projectionMapper;

    public void hydrateTrustedContext(AgentGatewayDtos.ChatRequest request) {
        request.setRecent_history(List.of());
        request.setHistory_summary(emptySummary());
        if (request.getSession_id() == null) {
            return;
        }

        ChatSession session = chatSessionMapper.selectById(request.getSession_id());
        if (session == null || !belongsToUser(session, request.getUser_id())) {
            throw new BizException(404, "会话不存在");
        }

        request.setOrder_id(stringId(session.getOrderId()));
        request.setTicket_id(stringId(session.getTicketId()));

        List<ChatMessage> newestFirst = chatMessageMapper.selectList(
                new LambdaQueryWrapper<ChatMessage>()
                        .eq(ChatMessage::getSessionId, session.getId())
                        .orderByDesc(ChatMessage::getCreateTime)
                        .orderByDesc(ChatMessage::getId)
                        .last("LIMIT " + CONTEXT_WINDOW_LIMIT)
        );
        List<ChatMessage> chronological = new ArrayList<>(newestFirst == null ? List.of() : newestFirst);
        Collections.reverse(chronological);
        List<ChatMessage> nonBlankMessages = chronological.stream()
                .filter(message -> message.getContent() != null && !message.getContent().isBlank())
                .toList();
        int recentStart = Math.max(0, nonBlankMessages.size() - RECENT_MESSAGE_LIMIT);
        List<ChatMessage> summarizedMessages = nonBlankMessages.subList(0, recentStart);
        List<AgentGatewayDtos.ConversationMessageDto> history = nonBlankMessages.subList(
                        recentStart,
                        nonBlankMessages.size())
                .stream()
                .map(this::toConversationMessage)
                .toList();
        request.setRecent_history(history);

        Map<String, Object> summary = emptySummary();
        summary.put("session_id", stringId(session.getId()));
        summary.put("session_mode", session.getMode());
        summary.put("session_status", session.getStatus());
        summary.put("order_id", stringId(session.getOrderId()));
        summary.put("ticket_id", stringId(session.getTicketId()));
        summary.put("policy_code", session.getPolicyCode());
        summary.put("policy_version", session.getPolicyVersion());
        summary.put("message_count", history.size());
        summary.put("window_message_count", nonBlankMessages.size());
        summary.put("conversation_summary_authoritative", false);
        summary.put("conversation_summary_type", "deterministic_mysql_window");
        summary.put("conversation_summary", summarizeMessages(summarizedMessages));
        summary.put("summary_through_message_id", summarizedMessages.isEmpty()
                ? null
                : stringId(summarizedMessages.get(summarizedMessages.size() - 1).getId()));
        Map<String, Object> projection = loadOrRebuildProjection(session.getId(), nonBlankMessages);
        String goalText = projection == null ? null : (String) projection.get("goal_text");
        String goalMessageId = projection == null ? null : Objects.toString(projection.get("goal_message_id"), null);
        summary.put("current_user_goal", StringUtils.hasText(goalText) ? goalText : currentUserGoal(nonBlankMessages));
        summary.put("current_user_goal_message_id", StringUtils.hasText(goalMessageId)
                ? goalMessageId : currentUserGoalMessageId(nonBlankMessages));
        summary.put("current_goal_status", Integer.valueOf(1).equals(session.getResolved())
                ? "resolved" : (projection == null ? "unknown" : projection.get("goal_status")));
        summary.put("projection_last_message_id", projection == null ? null : Objects.toString(projection.get("last_message_id"), null));
        summary.put("current_message_id", nonBlankMessages.isEmpty() ? null
                : stringId(nonBlankMessages.get(nonBlankMessages.size() - 1).getId()));
        summary.put("user_claims", recentUserClaims(nonBlankMessages));
        summary.put("user_claim_refs", recentUserClaimRefs(nonBlankMessages));
        summary.put("evidence_refs", recentEvidenceRefs(session.getId()));
        summary.put("open_questions", openQuestions(nonBlankMessages));
        request.setHistory_summary(summary);
    }

    @Transactional(rollbackFor = Exception.class)
    public void persistCurrentUserMessage(AgentGatewayDtos.ChatRequest request) {
        if (request.getSession_id() == null || !StringUtils.hasText(request.getMessage())) {
            return;
        }
        ChatSession session = chatSessionMapper.selectById(request.getSession_id());
        if (session == null || !belongsToUser(session, request.getUser_id())) {
            throw new BizException(404, "会话不存在");
        }

        LocalDateTime now = LocalDateTime.now();
        ChatMessage message = new ChatMessage();
        message.setSessionId(session.getId());
        message.setRole("USER");
        message.setMessageType("TEXT");
        message.setContent(request.getMessage().trim());
        message.setCreateTime(now);
        chatMessageMapper.insert(message);

        Map<String, Object> previous = loadOrRebuildProjection(session.getId(), List.of());
        Map<String, Object> historySummary = request.getHistory_summary();
        String oldGoal = previous == null
                ? Objects.toString(historySummary == null ? null : historySummary.get("current_user_goal"), "")
                : Objects.toString(previous.get("goal_text"), "");
        Long oldGoalId = asLong(previous == null
                ? (historySummary == null ? null : historySummary.get("current_user_goal_message_id"))
                : previous.get("goal_message_id"));
        boolean newGoal = !StringUtils.hasText(oldGoal) || startsNewGoal(message.getContent());
        if (request.getHistory_summary() != null) {
            request.getHistory_summary().put("current_message_id", stringId(message.getId()));
            request.getHistory_summary().put("goal_relation", newGoal ? "NEW_GOAL"
                    : isSupplement(request) ? "SUPPLEMENT" : "UNCERTAIN");
            if (newGoal) {
                request.getHistory_summary().put("current_user_goal", compactText(message.getContent(), USER_GOAL_MAX_CHARS));
                request.getHistory_summary().put("current_user_goal_message_id", stringId(message.getId()));
                request.getHistory_summary().put("current_goal_status", "active");
            }
        }
        try {
            projectionMapper.saveIfNewer(session.getId(), message.getId(),
                    newGoal ? message.getId() : oldGoalId,
                    newGoal ? compactText(message.getContent(), USER_GOAL_MAX_CHARS) : oldGoal,
                    "active");
        } catch (DataAccessException ignored) {
            // Projection is rebuildable from chat_message; message persistence remains authoritative.
        }

        session.setUserQuery(compactText(message.getContent(), USER_GOAL_MAX_CHARS));
        session.setUserHidden(0);
        session.setUpdateTime(now);
        chatSessionMapper.updateById(session);
    }

    private boolean belongsToUser(ChatSession session, String userId) {
        try {
            return userId != null && Objects.equals(session.getUserId(), Long.valueOf(userId));
        } catch (NumberFormatException ignored) {
            return false;
        }
    }

    private AgentGatewayDtos.ConversationMessageDto toConversationMessage(ChatMessage message) {
        AgentGatewayDtos.ConversationMessageDto dto = new AgentGatewayDtos.ConversationMessageDto();
        dto.setMessage_id(stringId(message.getId()));
        dto.setCreate_time(message.getCreateTime() == null ? null : message.getCreateTime().toString());
        dto.setRole("USER".equalsIgnoreCase(message.getRole()) ? "user" : "assistant");
        dto.setContent(message.getContent());
        return dto;
    }

    private Map<String, Object> emptySummary() {
        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("source", "mysql");
        summary.put("authoritative", true);
        summary.put("message_count", 0);
        return summary;
    }

    private String summarizeMessages(List<ChatMessage> messages) {
        StringBuilder summary = new StringBuilder();
        for (ChatMessage message : messages) {
            String role = "USER".equalsIgnoreCase(message.getRole()) ? "用户" : "客服";
            String content = compactText(message.getContent(), 180);
            if (content.isBlank()) {
                continue;
            }
            String item = role + "：" + content;
            if (summary.length() > 0) {
                item = "；" + item;
            }
            if (summary.length() + item.length() > SUMMARY_MAX_CHARS) {
                int remaining = SUMMARY_MAX_CHARS - summary.length();
                if (remaining > 0) {
                    summary.append(item, 0, Math.min(remaining, item.length()));
                }
                break;
            }
            summary.append(item);
        }
        return summary.toString();
    }

    private String currentUserGoal(List<ChatMessage> messages) {
        for (int index = messages.size() - 1; index >= 0; index--) {
            ChatMessage message = messages.get(index);
            if ("USER".equalsIgnoreCase(message.getRole())) {
                return compactText(message.getContent(), USER_GOAL_MAX_CHARS);
            }
        }
        return "";
    }

    private String currentUserGoalMessageId(List<ChatMessage> messages) {
        for (int index = messages.size() - 1; index >= 0; index--) {
            ChatMessage message = messages.get(index);
            if ("USER".equalsIgnoreCase(message.getRole())) {
                return stringId(message.getId());
            }
        }
        return null;
    }

    private Map<String, Object> loadProjection(Long sessionId) {
        try {
            return projectionMapper.find(sessionId);
        } catch (DataAccessException ignored) {
            return null;
        }
    }

    private Map<String, Object> loadOrRebuildProjection(Long sessionId, List<ChatMessage> recent) {
        Map<String, Object> projection = loadProjection(sessionId);
        Long lastProjected = asLong(projection == null ? null : projection.get("last_message_id"));
        Long latestUser = null;
        for (int index = recent.size() - 1; index >= 0; index--) {
            if ("USER".equalsIgnoreCase(recent.get(index).getRole())) {
                latestUser = recent.get(index).getId();
                break;
            }
        }
        if (projection != null && (latestUser == null || (lastProjected != null && lastProjected >= latestUser))) {
            return projection;
        }
        List<ChatMessage> userMessages = chatMessageMapper.selectList(
                new LambdaQueryWrapper<ChatMessage>()
                        .eq(ChatMessage::getSessionId, sessionId)
                        .eq(ChatMessage::getRole, "USER")
                        .orderByAsc(ChatMessage::getId));
        if (userMessages == null || userMessages.isEmpty()) {
            return projection;
        }
        ChatMessage goal = null;
        for (ChatMessage item : userMessages) {
            if ("USER".equalsIgnoreCase(item.getRole()) && StringUtils.hasText(item.getContent())
                    && (goal == null || startsNewGoal(item.getContent()))) {
                goal = item;
            }
        }
        if (goal == null) {
            return projection;
        }
        ChatMessage last = userMessages.stream()
                .filter(item -> "USER".equalsIgnoreCase(item.getRole()))
                .reduce((left, right) -> right).orElse(goal);
        Map<String, Object> rebuilt = new LinkedHashMap<>();
        rebuilt.put("last_message_id", last.getId());
        rebuilt.put("goal_message_id", goal.getId());
        rebuilt.put("goal_text", compactText(goal.getContent(), USER_GOAL_MAX_CHARS));
        rebuilt.put("goal_status", "active");
        try {
            projectionMapper.saveIfNewer(sessionId, last.getId(), goal.getId(),
                    (String) rebuilt.get("goal_text"), "active");
        } catch (DataAccessException ignored) {
            // History remains the fallback when the derived projection is unavailable.
        }
        return rebuilt;
    }

    private Long asLong(Object value) {
        if (value instanceof Number number) {
            return number.longValue();
        }
        try {
            return value == null ? null : Long.valueOf(value.toString());
        } catch (NumberFormatException ignored) {
            return null;
        }
    }

    private boolean startsNewGoal(String text) {
        String normalized = compactText(text, USER_GOAL_MAX_CHARS);
        return normalized.matches(".*(申请|想要|我要|咨询|查询|投诉|复核).*(退款|退货|换货|维修|售后|物流|订单|人工).*" )
                || normalized.matches(".*(退款|退货|换货|维修|售后|物流|订单|人工).*(怎么办|怎么样|如何|吗|？|\\?).*");
    }

    private boolean isSupplement(AgentGatewayDtos.ChatRequest request) {
        String text = compactText(request.getMessage(), USER_GOAL_MAX_CHARS);
        return (request.getAttachments() != null && !request.getAttachments().isEmpty())
                || text.matches(".*(补充|上传|已发|再提供|重新拍|新凭证).*" );
    }

    private List<Map<String, String>> recentUserClaimRefs(List<ChatMessage> messages) {
        List<Map<String, String>> claims = new ArrayList<>();
        for (int index = messages.size() - 1; index >= 0 && claims.size() < 5; index--) {
            ChatMessage message = messages.get(index);
            if ("USER".equalsIgnoreCase(message.getRole())) {
                claims.add(Map.of("message_id", stringId(message.getId()),
                        "text", compactText(message.getContent(), 240), "trust", "claimed"));
            }
        }
        Collections.reverse(claims);
        return claims;
    }

    private List<Map<String, String>> recentEvidenceRefs(Long sessionId) {
        List<Map<String, String>> refs = new ArrayList<>();
        List<ChatMessage> messages = chatMessageMapper.selectList(
                new LambdaQueryWrapper<ChatMessage>()
                        .eq(ChatMessage::getSessionId, sessionId)
                        .eq(ChatMessage::getRole, "USER")
                        .eq(ChatMessage::getMessageType, "IMAGE")
                        .orderByDesc(ChatMessage::getId)
                        .last("LIMIT 20"));
        if (messages == null) {
            return refs;
        }
        for (ChatMessage message : messages) {
            if ("IMAGE".equalsIgnoreCase(message.getMessageType()) && StringUtils.hasText(message.getFileUrl())) {
                refs.add(Map.of("message_id", stringId(message.getId()), "source", "chat_message"));
            }
        }
        return refs;
    }

    private List<Map<String, String>> openQuestions(List<ChatMessage> messages) {
        for (int index = messages.size() - 1; index >= 0; index--) {
            ChatMessage message = messages.get(index);
            if ("USER".equalsIgnoreCase(message.getRole())) {
                return List.of();
            }
            String content = message.getContent();
            if ("ASSISTANT".equalsIgnoreCase(message.getRole()) && content != null
                    && (content.endsWith("？") || content.endsWith("?"))) {
                return List.of(Map.of("message_id", stringId(message.getId()),
                        "text", compactText(content, 240), "status", "unknown"));
            }
        }
        return List.of();
    }

    private List<String> recentUserClaims(List<ChatMessage> messages) {
        List<String> claims = new ArrayList<>();
        for (int index = messages.size() - 1; index >= 0 && claims.size() < 5; index--) {
            ChatMessage message = messages.get(index);
            if ("USER".equalsIgnoreCase(message.getRole())) {
                String claim = compactText(message.getContent(), 240);
                if (!claim.isBlank() && !claims.contains(claim)) {
                    claims.add(claim);
                }
            }
        }
        Collections.reverse(claims);
        return claims;
    }

    private String compactText(String value, int limit) {
        if (value == null) {
            return "";
        }
        String normalized = value.replaceAll("\\s+", " ").trim();
        return normalized.length() <= limit ? normalized : normalized.substring(0, limit);
    }

    private String stringId(Long value) {
        return value == null ? null : value.toString();
    }
}
