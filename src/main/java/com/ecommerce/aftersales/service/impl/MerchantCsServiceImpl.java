package com.ecommerce.aftersales.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.common.PageResult;
import com.ecommerce.aftersales.config.ChatWebSocketHandler;
import com.ecommerce.aftersales.dto.AgentGatewayDtos;
import com.ecommerce.aftersales.dto.MerchantCsDtos.*;
import com.ecommerce.aftersales.dto.WsChatMessage;
import com.ecommerce.aftersales.entity.*;
import com.ecommerce.aftersales.mapper.*;
import com.ecommerce.aftersales.service.AgentGatewayService;
import com.ecommerce.aftersales.service.ChatEmotionAnalysisService;
import com.ecommerce.aftersales.service.KnowledgeRetrievalService;
import com.ecommerce.aftersales.service.MerchantCsService;
import com.ecommerce.aftersales.service.NotificationService;
import com.ecommerce.aftersales.service.VerificationCodeService;
import com.ecommerce.aftersales.util.JwtTokenUtil;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.math.BigDecimal;
import java.time.Duration;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.stream.Collectors;

@Slf4j
@Service
@RequiredArgsConstructor
public class MerchantCsServiceImpl implements MerchantCsService {

    private static final String DEFAULT_MERCHANT_CODE = "MERCHANT_DEMO";
    private static final String REGISTER_SCENE = "REGISTER";
    private static final String RESET_PASSWORD_SCENE = "RESET_PASSWORD";
    private static final Duration EVALUATION_TIMEOUT = Duration.ofMinutes(30);
    private static final DateTimeFormatter DATE_TIME_FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final SysUserMapper sysUserMapper;
    private final ChatSessionMapper chatSessionMapper;
    private final ChatMessageMapper chatMessageMapper;
    private final AfterSalesTicketMapper afterSalesTicketMapper;
    private final TicketLogMapper ticketLogMapper;
    private final TicketAttachmentMapper ticketAttachmentMapper;
    private final OrderInfoMapper orderInfoMapper;
    private final OrderItemMapper orderItemMapper;
    private final ProductInfoMapper productInfoMapper;
    private final UserMapper userMapper;
    private final MessageNoticeMapper messageNoticeMapper;
    private final AgentGatewayService agentGatewayService;
    private final ChatEmotionAnalysisService chatEmotionAnalysisService;
    private final KnowledgeRetrievalService knowledgeRetrievalService;
    private final PasswordEncoder passwordEncoder;
    private final JwtTokenUtil jwtTokenUtil;
    private final ObjectMapper objectMapper;
    private final ChatWebSocketHandler chatWebSocketHandler;
    private final NotificationService notificationService;
    private final VerificationCodeService verificationCodeService;

    @Override
    @Transactional(rollbackFor = Exception.class)
    public LoginResponse login(LoginRequest request) {
        if (!StringUtils.hasText(request.getAccount()) || !StringUtils.hasText(request.getPassword())) {
            throw new BizException("账号和密码不能为空");
        }
        SysUser staff = findStaffByAccount(request.getAccount());
        if (staff == null || !passwordEncoder.matches(request.getPassword(), staff.getPassword())) {
            throw new BizException("账号或密码错误");
        }
        if (!Integer.valueOf(1).equals(staff.getStatus())) {
            throw new BizException(403, "客服账号不可用");
        }
        if (!StringUtils.hasText(staff.getMerchantCode())) {
            staff.setMerchantCode(DEFAULT_MERCHANT_CODE);
        }
        staff.setOnlineStatus(1);
        staff.setLastLoginTime(LocalDateTime.now());
        sysUserMapper.updateById(staff);

        LoginResponse response = new LoginResponse();
        response.setToken(jwtTokenUtil.generateToken(staff.getId(), Optional.ofNullable(staff.getPhone()).orElse(staff.getUsername())));
        response.setStaff(toStaffProfile(staff));
        return response;
    }

    @Override
    public String sendAuthCode(AuthCodeRequest request) {
        String scene = normalizeAuthScene(request == null ? null : request.getScene());
        String phone = normalizePhone(request == null ? null : request.getPhone());
        if (!StringUtils.hasText(phone)) {
            throw new BizException("请输入手机号");
        }
        if (REGISTER_SCENE.equals(scene)) {
            if (request != null && StringUtils.hasText(request.getAccount()) && findStaffByAccount(request.getAccount()) != null) {
                throw new BizException("账号已存在，请更换其他账号");
            }
            return verificationCodeService.sendCode(phone, REGISTER_SCENE);
        }

        String account = request == null ? null : request.getAccount();
        if (!StringUtils.hasText(account)) {
            throw new BizException("请输入登录账号");
        }
        SysUser staff = findStaffByAccount(account);
        if (staff == null) {
            throw new BizException("账号不存在");
        }
        String boundPhone = normalizePhone(staff.getPhone());
        if (!StringUtils.hasText(boundPhone)) {
            throw new BizException("该账号未绑定手机号，请联系管理员处理");
        }
        if (!boundPhone.equals(phone)) {
            throw new BizException("账号与手机号不匹配");
        }
        return verificationCodeService.sendCode(phone, RESET_PASSWORD_SCENE);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public StaffProfile register(RegisterRequest request) {
        if (!StringUtils.hasText(request.getAccount())
                || !StringUtils.hasText(request.getPassword())
                || !StringUtils.hasText(request.getRealName())
                || !StringUtils.hasText(request.getPhone())
                || !StringUtils.hasText(request.getCode())) {
            throw new BizException("请填写账号、密码、姓名和商家编码");
        }
        verificationCodeService.verifyCode(normalizePhone(request.getPhone()), REGISTER_SCENE, request.getCode());
        if (findStaffByAccount(request.getAccount()) != null) {
            throw new BizException("该商家下账号已存在");
        }

        SysUser staff = new SysUser();
        staff.setUsername(request.getAccount().trim());
        staff.setPassword(passwordEncoder.encode(request.getPassword()));
        staff.setMerchantCode(DEFAULT_MERCHANT_CODE);
        staff.setRealName(request.getRealName().trim());
        staff.setPhone(normalizePhone(request.getPhone()));
        staff.setRoleType("AGENT");
        staff.setStatus(1);
        staff.setOnlineStatus(0);
        staff.setMaxSessions(8);
        staff.setDeleted(0);
        sysUserMapper.insert(staff);
        staff.setMerchantCode(buildAutoMerchantCode(staff.getId()));
        sysUserMapper.updateById(staff);
        return toStaffProfile(staff);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void resetPassword(ResetPasswordRequest request) {
        if (request == null
                || !StringUtils.hasText(request.getAccount())
                || !StringUtils.hasText(request.getPhone())
                || !StringUtils.hasText(request.getCode())
                || !StringUtils.hasText(request.getNewPassword())
                || !StringUtils.hasText(request.getConfirmPassword())) {
            throw new BizException("请填写账号、手机号、验证码和新密码");
        }
        if (!request.getNewPassword().equals(request.getConfirmPassword())) {
            throw new BizException("两次输入的密码不一致");
        }
        SysUser staff = findStaffByAccount(request.getAccount());
        if (staff == null) {
            throw new BizException("账号不存在");
        }
        String phone = normalizePhone(request.getPhone());
        if (!phone.equals(normalizePhone(staff.getPhone()))) {
            throw new BizException("账号与手机号不匹配");
        }
        verificationCodeService.verifyCode(phone, RESET_PASSWORD_SCENE, request.getCode());
        staff.setPassword(passwordEncoder.encode(request.getNewPassword()));
        sysUserMapper.updateById(staff);
    }

    @Override
    public void logout() {
    }

    @Override
    public StaffProfile getCurrentStaff() {
        return toStaffProfile(ensureStaff());
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public StaffProfile updateWorkStatus(String onlineStatus) {
        SysUser staff = ensureStaff();
        staff.setOnlineStatus(toOnlineStatusValue(onlineStatus));
        sysUserMapper.updateById(staff);
        return toStaffProfile(staff);
    }

    @Override
    public DashboardOverview getDashboardOverview() {
        StaffProfile staff = getCurrentStaff();
        List<SessionView> sessions = allSessions();
        List<TicketView> tickets = allTickets();
        long waitingSessions = sessions.stream().filter(item -> List.of("WAITING", "PROCESSING").contains(item.getStatus())).count();
        long pendingTickets = tickets.stream().filter(item -> "PENDING_REVIEW".equals(item.getStatus())).count();
        long warningTickets = tickets.stream().filter(item -> "HIGH".equals(item.getPriority())).count();

        DashboardOverview overview = new DashboardOverview();
        overview.setGreeting("您好，" + staff.getRealName());
        overview.setTodayTodoCount((int) (waitingSessions + pendingTickets + warningTickets));
        overview.setSubtitle("当前还有 " + overview.getTodayTodoCount() + " 项任务待处理");
        overview.setAiEnabled(true);
        overview.setMetrics(List.of(
                metric("待接入会话", waitingSessions, "+0", "orange"),
                metric("待审核申请", pendingTickets, "+0", "slate"),
                metric("超时预警", warningTickets, "+0", "green")
        ));
        overview.setTimeline(buildTimeline());
        return overview;
    }

    @Override
    public List<TodoItem> getDashboardTodos() {
        List<TodoItem> todos = new ArrayList<>();
        for (TicketView ticket : allTickets().stream().filter(item -> "PENDING_REVIEW".equals(item.getStatus())).limit(5).toList()) {
            TodoItem item = new TodoItem();
            item.setId(ticket.getId());
            item.setTitle("售后申请 #" + ticket.getTicketNo());
            item.setTag(ticket.getAfterSalesType());
            item.setAmount(Optional.ofNullable(ticket.getApplyRefundAmount()).orElse("0.00") + " 元");
            item.setPriority(ticket.getPriority());
            item.setPriorityTone("HIGH".equals(ticket.getPriority()) ? "high" : "normal");
            item.setAction("审核");
            item.setTarget("/tickets/" + ticket.getId());
            todos.add(item);
        }
        for (SessionView session : allSessions().stream().filter(item -> "WAITING".equals(item.getStatus())).limit(5).toList()) {
            TodoItem item = new TodoItem();
            item.setId(session.getId());
            item.setTitle("会话 #" + session.getSessionNo());
            item.setTag("人工介入");
            item.setAmount(Optional.ofNullable(session.getEmotion()).orElse("待处理"));
            item.setPriority("HIGH".equals(session.getLevel()) ? "HIGH" : "NORMAL");
            item.setPriorityTone("high");
            item.setAction("接入");
            item.setTarget("/sessions/" + session.getId());
            todos.add(item);
        }
        return todos;
    }

    @Override
    public DashboardPerformance getDashboardPerformance() {
        DashboardPerformance performance = new DashboardPerformance();
        performance.setMetrics(List.of(
                performanceMetric("30 秒响应率", "92%", "目标 90%", 92, 90),
                performanceMetric("一次解决率", "68%", "目标 70%", 68, 70),
                performanceMetric("平均处理时长", "06:24", "目标 08:00", 80, 100)
        ));
        return performance;
    }

    @Override
    public PageResult<SessionView> listSessions(long page, long size, String status, String keyword) {
        List<SessionView> records = allSessions().stream()
                .filter(item -> !StringUtils.hasText(status) || status.equals(item.getStatus()))
                .filter(item -> !StringUtils.hasText(keyword) || containsAny(keyword, item.getSessionNo(), item.getUser(), item.getTopic(), item.getLastMessageContent()))
                .toList();
        return PageResult.of(records, page, size);
    }

    @Override
    public SessionView getSession(Long sessionId) {
        ChatSession session = findSession(sessionId);
        return toSessionView(session);
    }

    @Override
    public List<MessageView> listSessionMessages(Long sessionId) {
        findSession(sessionId);
        List<ChatMessage> messages = chatMessageMapper.selectList(new LambdaQueryWrapper<ChatMessage>()
                        .eq(ChatMessage::getSessionId, sessionId)
                        .orderByAsc(ChatMessage::getCreateTime));
        chatEmotionAnalysisService.backfillMissingEmotions(sessionId, messages);
        return messages.stream()
                .map(this::toMessageView)
                .toList();
    }

    @Override
    public SessionAiAssistView getSessionAiAssist(Long sessionId) {
        ChatSession session = findSession(sessionId);
        List<ChatMessage> messageEntities = chatMessageMapper.selectList(new LambdaQueryWrapper<ChatMessage>()
                .eq(ChatMessage::getSessionId, sessionId)
                .orderByAsc(ChatMessage::getCreateTime));
        chatEmotionAnalysisService.backfillMissingEmotions(sessionId, messageEntities);
        OrderInfo order = session.getOrderId() == null ? null : orderInfoMapper.selectById(session.getOrderId());
        AfterSalesTicket ticket = session.getTicketId() == null ? null : afterSalesTicketMapper.selectById(session.getTicketId());
        ChatMessage latestUserMessage = latestUserMessage(messageEntities);
        String latestUserText = firstNonBlank(
                latestUserMessage == null ? null : latestUserMessage.getContent(),
                session.getUserQuery(),
                "请帮我处理当前用户问题"
        );

        AgentGatewayDtos.AssistReplyResponse assistReply = fetchAssistReply(session, messageEntities, order, ticket, latestUserText);
        String intentCode = resolveAssistIntent(assistReply, latestUserText);
        String sceneCode = resolveAssistScene(assistReply, latestUserText, ticket);
        AgentGatewayDtos.KnowledgeRetrieveResponse quickReplyKnowledge = fetchQuickReplyKnowledge(
                latestUserText,
                order,
                sceneCode,
                intentCode
        );

        List<QuickReplyView> quickReplyViews = buildQuickReplyViews(quickReplyKnowledge);
        RecommendationView recommendation = buildRecommendationView(assistReply, latestUserText, sceneCode);
        Map<String, String> conversationDigest = buildConversationDigest(
                session,
                order,
                ticket,
                messageEntities,
                assistReply,
                intentCode,
                sceneCode,
                recommendation
        );
        SessionAiAssistView view = new SessionAiAssistView();
        view.setSessionId(sessionId);
        view.setLatestUserMessage(latestUserText);
        view.setIntentCode(intentCode);
        view.setSceneCode(sceneCode);
        view.setRecommendation(recommendation);
        view.setStaffSuggestion(selectStaffSuggestion(assistReply));
        view.setQuickReplies(quickReplyViews);
        view.setQuickReplySource("reply_template_knowledge");
        view.setKnowledgeQuery(assistReply == null ? latestUserText : assistReply.getKnowledge_query());
        view.setKnowledgeRetrievalMode(assistReply == null ? null : assistReply.getKnowledge_retrieval_mode());
        view.setKnowledgeHits(mapKnowledgeHits(assistReply == null ? List.of() : assistReply.getKnowledge_hits()));
        view.setHandoffSummary(assistReply == null ? null : assistReply.getHandoff_summary());
        view.setConversationDigest(conversationDigest);
        view.setHandoffSummaryText(formatConversationDigestText(conversationDigest));
        view.setTrace(buildAssistTrace(assistReply, quickReplyKnowledge));
        return view;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public MessageView sendSessionMessage(Long sessionId, SendMessageRequest request) {
        ChatSession session = findSession(sessionId);
        if (!StringUtils.hasText(request.getContent())) {
            throw new BizException("消息内容不能为空");
        }
        SysUser staff = ensureStaff();
        ChatMessage message = new ChatMessage();
        message.setSessionId(sessionId);
        message.setRole("ASSISTANT");
        message.setMessageType(StringUtils.hasText(request.getMessageType()) ? request.getMessageType() : "TEXT");
        message.setContent(request.getContent());
        chatMessageMapper.insert(message);
        if ("WAITING".equals(session.getStatus())) {
            session.setStatus("ACTIVE");
            session.setHumanAgentId(staff.getId());
            chatSessionMapper.updateById(session);
        }
        // Broadcast staff message via WebSocket
        broadcastToSession(sessionId, message);

        // Notify user about merchant reply
        notificationService.createNotification(
                session.getUserId(),
                "客服已回复",
                "客服回复了您的咨询：" + (request.getContent().length() > 50
                        ? request.getContent().substring(0, 50) + "..."
                        : request.getContent()),
                "CHAT",
                sessionId,
                "CHAT_SESSION"
        );

        return toMessageView(message);
    }

    private void broadcastToSession(Long sessionId, ChatMessage message) {
        try {
            chatWebSocketHandler.broadcastToSession(sessionId, WsChatMessage.builder()
                    .action("message")
                    .sessionId(sessionId)
                    .id(message.getId())
                    .role(message.getRole())
                    .content(message.getContent())
                    .messageType(message.getMessageType())
                    .createdAt(message.getCreateTime() == null
                            ? LocalDateTime.now().format(DATE_TIME_FORMATTER)
                            : DATE_TIME_FORMATTER.format(message.getCreateTime()))
                    .emotionLabel(message.getEmotionLabel())
                    .emotionScore(message.getEmotionScore())
                    .emotionConfidence(message.getEmotionConfidence())
                    .build());
        } catch (Exception ignored) {
            // WebSocket broadcast failure should not break the HTTP response
        }
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public SessionView requestSessionEvaluation(Long sessionId) {
        ChatSession session = findSession(sessionId);
        if (!"PROCESSING".equals(toMerchantSessionStatus(session))) {
            throw new BizException("只有处理中会话才能发送评价请求");
        }
        LocalDateTime now = LocalDateTime.now();
        session.setStatus("AWAITING_EVALUATION");
        session.setResolved(0);
        session.setUpdateTime(now);
        chatSessionMapper.updateById(session);
        addSystemMessage(sessionId, "已发送服务评价邀请，等待用户评价。");
        notificationService.createNotification(
                session.getUserId(),
                "请评价本次客服服务",
                "您的售后问题已处理完成，请对本次客服服务进行评价。",
                "CHAT",
                sessionId,
                "CHAT_SESSION"
        );
        return toSessionView(session);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public SessionView submitSessionEvaluation(Long sessionId, EvaluationRequest request) {
        ChatSession session = findSession(sessionId);
        if (!"AWAITING_EVALUATION".equals(session.getStatus())) {
            throw new BizException("当前会话不在待评价状态");
        }
        LocalDateTime now = LocalDateTime.now();
        session.setResolved(1);
        session.setSatisfaction(request.getRating() == null ? 5 : request.getRating());
        session.setStatus("READY_TO_CLOSE");
        session.setCloseTime(now);
        session.setUpdateTime(now);
        chatSessionMapper.updateById(session);
        addSystemMessage(sessionId, StringUtils.hasText(request.getContent()) ? request.getContent() : "用户已完成服务评价");
        return toSessionView(session);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public SessionView closeSession(Long sessionId) {
        ChatSession session = findSession(sessionId);
        if (!canCloseSession(session)) {
            throw new BizException("只有用户已评价或评价已超时的会话才能关闭");
        }
        LocalDateTime now = LocalDateTime.now();
        session.setStatus("CLOSED");
        session.setCloseTime(now);
        session.setUpdateTime(now);
        chatSessionMapper.updateById(session);
        addSystemMessage(sessionId, "会话已由客服关闭。");
        return toSessionView(session);
    }

    @Override
    public PageResult<TicketView> listTickets(long page, long size, String status, String type, String keyword) {
        List<TicketView> records = allTickets().stream()
                .filter(item -> !StringUtils.hasText(status) || status.equals(item.getStatus()))
                .filter(item -> !StringUtils.hasText(type) || type.equals(item.getAfterSalesType()))
                .filter(item -> !StringUtils.hasText(keyword) || containsAny(keyword, item.getTicketNo(), item.getOrderNo(), item.getTitle(), item.getReasonType()))
                .toList();
        return PageResult.of(records, page, size);
    }

    @Override
    public TicketView getTicket(Long ticketId) {
        return toTicketView(findTicket(ticketId));
    }

    @Override
    public List<TicketLogView> listTicketLogs(Long ticketId) {
        findTicket(ticketId);
        return ticketLogMapper.selectList(new LambdaQueryWrapper<TicketLog>()
                        .eq(TicketLog::getTicketId, ticketId)
                        .orderByAsc(TicketLog::getCreateTime))
                .stream()
                .map(this::toTicketLogView)
                .toList();
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public TicketView approveTicket(Long ticketId, String auditOpinion) {
        AfterSalesTicket ticket = findTicket(ticketId);
        if (!"PENDING".equals(ticket.getStatus()) && !"PENDING_REVIEW".equals(ticket.getStatus())) {
            throw new BizException("只有待审核状态的申请才能审核通过");
        }
        String oldStatus = ticket.getStatus();
        ticket.setStatus("PROCESSING");
        ticket.setAuditOpinion(StringUtils.hasText(auditOpinion) ? auditOpinion : "审核通过，进入处理中");
        ticket.setAuditTime(LocalDateTime.now());
        ticket.setAssigneeId(ensureStaff().getId());
        afterSalesTicketMapper.updateById(ticket);
        addTicketLog(ticket, oldStatus, "PROCESSING", "APPROVE", ticket.getAuditOpinion());
        // Notify user about approval
        notificationService.createNotification(
                ticket.getUserId(),
                "售后申请审核通过",
                "您的售后申请 " + ticket.getTicketNo() + " 已审核通过，当前处理中",
                "AFTER_SALE",
                ticket.getId(),
                "TICKET"
        );
        return toTicketView(ticket);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public TicketView rejectTicket(Long ticketId, String rejectReason) {
        AfterSalesTicket ticket = findTicket(ticketId);
        if (!"PENDING".equals(ticket.getStatus()) && !"PENDING_REVIEW".equals(ticket.getStatus())) {
            throw new BizException("只有待审核状态的申请才能驳回");
        }
        String oldStatus = ticket.getStatus();
        ticket.setStatus("REJECTED");
        ticket.setAuditOpinion(StringUtils.hasText(rejectReason) ? rejectReason : "资料不足，请补充凭证");
        ticket.setAuditTime(LocalDateTime.now());
        ticket.setAssigneeId(ensureStaff().getId());
        afterSalesTicketMapper.updateById(ticket);
        addTicketLog(ticket, oldStatus, "REJECTED", "REJECT", ticket.getAuditOpinion());
        // Notify user about rejection
        notificationService.createNotification(
                ticket.getUserId(),
                "售后申请已驳回",
                "您的售后申请 " + ticket.getTicketNo() + " 已被驳回，原因：" + ticket.getAuditOpinion(),
                "AFTER_SALE",
                ticket.getId(),
                "TICKET"
        );
        return toTicketView(ticket);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public TicketView completeTicket(Long ticketId, String completeNote) {
        AfterSalesTicket ticket = findTicket(ticketId);
        if (!"PROCESSING".equals(ticket.getStatus())) {
            throw new BizException("只有处理中状态的申请才能标记为已完成");
        }
        String oldStatus = ticket.getStatus();
        ticket.setStatus("COMPLETED");
        ticket.setCompleteTime(LocalDateTime.now());
        ticket.setAuditOpinion(StringUtils.hasText(completeNote) ? completeNote : "处理完成");
        ticket.setAssigneeId(ensureStaff().getId());
        afterSalesTicketMapper.updateById(ticket);
        addTicketLog(ticket, oldStatus, "COMPLETED", "COMPLETE", ticket.getAuditOpinion());
        markRelatedSessionsReadyForEvaluation(ticket);
        // Notify user about completion
        notificationService.createNotification(
                ticket.getUserId(),
                "售后申请已处理完成",
                "您的售后申请 " + ticket.getTicketNo() + " 已处理完成",
                "AFTER_SALE",
                ticket.getId(),
                "TICKET"
        );
        return toTicketView(ticket);
    }

    @Override
    public PageResult<OrderView> listOrders(long page, long size, String status, String keyword) {
        List<OrderView> records = orderInfoMapper.selectList(new LambdaQueryWrapper<OrderInfo>()
                        .eq(OrderInfo::getMerchantCode, currentMerchantCode())
                        .orderByDesc(OrderInfo::getCreateTime))
                .stream()
                .map(this::toOrderView)
                .filter(item -> !StringUtils.hasText(status) || status.equals(item.getStatus()))
                .filter(item -> !StringUtils.hasText(keyword) || containsAny(keyword, item.getOrderNo(), item.getUser(), item.getProduct()))
                .toList();
        return PageResult.of(records, page, size);
    }

    @Override
    public OrderDetail getOrder(Long orderId) {
        OrderInfo order = findOrder(orderId);
        OrderDetail detail = new OrderDetail();
        User user = userMapper.selectById(order.getUserId());
        detail.setId(order.getId());
        detail.setOrderNo(order.getOrderNo());
        detail.setMerchantCode(order.getMerchantCode());
        detail.setUser(userDisplayName(user));
        detail.setPhone(maskPhone(order.getReceiverPhone()));
        detail.setAddress(order.getReceiverAddress());
        detail.setStatus(order.getStatus());
        detail.setPayAmount(money(order.getPayAmount()));
        detail.setPayTime(format(order.getPayTime()));
        detail.setProductItems(orderItems(order.getId()));
        LogisticsInfo logistics = new LogisticsInfo();
        logistics.setCompany(order.getTrackingCompany());
        logistics.setTrackingNo(order.getTrackingNo());
        logistics.setStatus(logisticsStatus(order));
        detail.setLogistics(logistics);
        detail.setRelatedTicketId(findTicketByOrderId(order.getId()).map(AfterSalesTicket::getId).orElse(null));
        return detail;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public OrderDetail shipOrder(Long orderId) {
        OrderInfo order = findOrder(orderId);
        if (!"PAID".equals(order.getStatus())) {
            throw new BizException("只有未发货订单可以执行发货");
        }
        order.setStatus("SHIPPED");
        order.setShipTime(LocalDateTime.now());
        if (!StringUtils.hasText(order.getTrackingCompany())) {
            order.setTrackingCompany("演示快递");
        }
        if (!StringUtils.hasText(order.getTrackingNo())) {
            order.setTrackingNo("DEMO" + System.currentTimeMillis());
        }
        orderInfoMapper.updateById(order);
        notificationService.createNotification(
                order.getUserId(),
                "订单已发货",
                "您的订单 " + order.getOrderNo() + " 已由商家发货，正在配送中",
                "ORDER",
                order.getId(),
                "ORDER"
        );
        return getOrder(orderId);
    }

    @Override
    public PageResult<NoticeView> listNotices(long page, long size, String readStatus, String level) {
        List<NoticeView> records = messageNoticeMapper.selectList(new LambdaQueryWrapper<MessageNotice>().orderByDesc(MessageNotice::getCreateTime))
                .stream()
                .map(this::toNoticeView)
                .filter(item -> !StringUtils.hasText(readStatus) || readStatus.equals(item.getReadStatus()))
                .filter(item -> !StringUtils.hasText(level) || level.equals(item.getLevel()))
                .toList();
        return PageResult.of(records, page, size);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public NoticeView markNoticeRead(Long noticeId) {
        MessageNotice notice = messageNoticeMapper.selectById(noticeId);
        if (notice == null) {
            throw new BizException(404, "通知不存在");
        }
        notice.setIsRead(1);
        notice.setReadTime(LocalDateTime.now());
        messageNoticeMapper.updateById(notice);
        return toNoticeView(notice);
    }

    @Override
    public PageResult<ProductView> listProducts(long page, long size, String status, String keyword) {
        List<ProductView> records = productInfoMapper.selectList(new LambdaQueryWrapper<ProductInfo>()
                        .eq(ProductInfo::getMerchantCode, currentMerchantCode())
                        .orderByDesc(ProductInfo::getCreateTime))
                .stream()
                .map(this::toProductView)
                .filter(item -> !StringUtils.hasText(status) || status.equals(item.getStatus()))
                .filter(item -> !StringUtils.hasText(keyword) || containsAny(keyword, item.getProductName(), item.getProductCode(), item.getCategory()))
                .toList();
        return PageResult.of(records, page, size);
    }

    @Override
    public ProductView getProduct(Long productId) {
        return toProductView(findProduct(productId));
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public ProductView createProduct(ProductUpsertRequest request) {
        ProductInfo product = new ProductInfo();
        applyProductRequest(product, request);
        SysUser staff = ensureStaff();
        product.setMerchantId(staff.getId());
        product.setMerchantCode(merchantCodeOf(staff));
        product.setDeleted(0);
        productInfoMapper.insert(product);
        return toProductView(product);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public ProductView updateProduct(Long productId, ProductUpsertRequest request) {
        ProductInfo product = findProduct(productId);
        applyProductRequest(product, request);
        productInfoMapper.updateById(product);
        return toProductView(product);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public ProductView updateProductStatus(Long productId, String status) {
        ProductInfo product = findProduct(productId);
        product.setStatus(toProductStatusValue(status));
        productInfoMapper.updateById(product);
        return toProductView(product);
    }

    private SysUser findStaffByAccount(String account) {
        return sysUserMapper.selectOne(new LambdaQueryWrapper<SysUser>()
                .eq(SysUser::getUsername, account)
                .eq(SysUser::getRoleType, "AGENT")
                .last("limit 1"));
    }

    private SysUser ensureStaff() {
        Long currentStaffId = currentStaffId();
        if (currentStaffId == null) {
            throw new BizException(401, "未登录，请先登录");
        }
        SysUser staff = sysUserMapper.selectById(currentStaffId);
        if (staff == null) {
            throw new BizException(401, "客服账号不存在或已禁用");
        }
        if (!Integer.valueOf(1).equals(staff.getStatus())) {
            throw new BizException(403, "客服账号已被禁用");
        }
        return staff;
    }

    private SysUser createDemoStaff(String merchantCode) {
        SysUser staff = new SysUser();
        staff.setUsername("cs_demo");
        staff.setPassword(passwordEncoder.encode("123456"));
        staff.setMerchantCode(merchantCode);
        staff.setRealName("林真");
        staff.setPhone("13800000001");
        staff.setEmail("cs_demo@example.com");
        staff.setRoleType("AGENT");
        staff.setStatus(1);
        staff.setOnlineStatus(1);
        staff.setMaxSessions(8);
        staff.setDeleted(0);
        sysUserMapper.insert(staff);
        return staff;
    }

    private StaffProfile toStaffProfile(SysUser staff) {
        StaffProfile profile = new StaffProfile();
        profile.setStaffId(staff.getId());
        profile.setStaffNo("CS" + String.format("%04d", staff.getId()));
        profile.setMerchantCode(merchantCodeOf(staff));
        profile.setAccount(staff.getUsername());
        profile.setRealName(staff.getRealName());
        profile.setPhone(staff.getPhone());
        profile.setRole("AGENT".equals(staff.getRoleType()) ? "CUSTOMER_SERVICE" : staff.getRoleType());
        profile.setOnlineStatus(toOnlineStatusText(staff.getOnlineStatus()));
        profile.setAccountStatus(Integer.valueOf(1).equals(staff.getStatus()) ? "ENABLED" : "DISABLED");
        profile.setMaxSessionCount(staff.getMaxSessions());
        return profile;
    }

    private List<SessionView> allSessions() {
        return chatSessionMapper.selectList(new LambdaQueryWrapper<ChatSession>()
                        .eq(ChatSession::getMerchantCode, currentMerchantCode())
                        .eq(ChatSession::getMode, "HUMAN")
                        .orderByDesc(ChatSession::getUpdateTime))
                .stream()
                .map(this::toSessionView)
                .toList();
    }

    private SessionView toSessionView(ChatSession session) {
        User user = userMapper.selectById(session.getUserId());
        OrderInfo order = session.getOrderId() == null ? null : orderInfoMapper.selectById(session.getOrderId());
        AfterSalesTicket ticket = session.getTicketId() == null ? null : afterSalesTicketMapper.selectById(session.getTicketId());
        ChatMessage lastMessage = lastMessage(session.getId()).orElse(null);

        SessionView view = new SessionView();
        view.setId(session.getId());
        view.setSessionNo(session.getSessionNo());
        view.setMerchantCode(session.getMerchantCode());
        view.setUserId(session.getUserId());
        view.setOrderId(session.getOrderId());
        view.setTicketId(session.getTicketId());
        view.setServiceId(session.getHumanAgentId());
        view.setUser(userDisplayName(user));
        view.setTopic(Optional.ofNullable(session.getUserQuery()).orElse("在线咨询"));
        view.setLevel(priorityLabel(ticket));
        view.setWait(waitText(session.getCreateTime()));
        view.setEmotion(emotionText(session.getEmotionLabel()));
        view.setEmotionLabel(normalizeEmotionLabel(session.getEmotionLabel()));
        view.setEmotionScore(session.getEmotionScore());
        view.setEmotionConfidence(session.getEmotionConfidence());
        view.setSourceChannel("小程序咨询");
        view.setServiceUnreadCount(0);
        view.setOrderNo(order == null ? null : order.getOrderNo());
        view.setProduct(ticket == null ? null : ticket.getProductName());
        view.setProductName(ticket == null ? null : ticket.getProductName());
        view.setTicketNo(ticket == null ? null : ticket.getTicketNo());
        view.setLastMessageContent(lastMessage == null ? null : lastMessage.getContent());
        view.setLastMessageTime(lastMessage == null ? format(session.getUpdateTime()) : format(lastMessage.getCreateTime()));
        view.setAiSummary(session.getUserQuery());
        view.setStatus(toMerchantSessionStatus(session));
        view.setRating(session.getSatisfaction());
        view.setEvaluationRequestedAt("AWAITING_EVALUATION".equals(session.getStatus()) ? format(session.getUpdateTime()) : null);
        view.setEvaluationStatus(evaluationStatus(session));
        view.setEvaluatedAt(session.getSatisfaction() == null ? null : format(session.getCloseTime()));
        return view;
    }

    private Optional<ChatMessage> lastMessage(Long sessionId) {
        return Optional.ofNullable(chatMessageMapper.selectOne(new LambdaQueryWrapper<ChatMessage>()
                .eq(ChatMessage::getSessionId, sessionId)
                .orderByDesc(ChatMessage::getCreateTime)
                .last("limit 1")));
    }

    private MessageView toMessageView(ChatMessage message) {
        MessageView view = new MessageView();
        view.setId(message.getId());
        view.setSessionId(message.getSessionId());
        view.setSenderRole("USER".equals(message.getRole()) ? "USER" : "SERVICE");
        view.setMessageType(message.getMessageType());
        view.setContent(message.getContent());
        view.setAiReplyConfidence(message.getConfidence());
        view.setEmotionLabel(normalizeEmotionLabel(message.getEmotionLabel()));
        view.setEmotionScore(message.getEmotionScore());
        view.setEmotionConfidence(message.getEmotionConfidence());
        view.setKnowledgeQuery(message.getKnowledgeQuery());
        view.setKnowledgeRetrievalMode(message.getKnowledgeRetrievalMode());
        view.setKnowledgeHitCount(message.getKnowledgeHitCount());
        view.setKnowledgeHits(parseKnowledgeHits(message.getKnowledgeHitsJson()));
        view.setKnowledgeTrace(parseKnowledgeTrace(message.getKnowledgeTraceJson()));
        view.setCreatedAt(format(message.getCreateTime()));
        return view;
    }

    private List<KnowledgeHitView> parseKnowledgeHits(String knowledgeHitsJson) {
        if (!StringUtils.hasText(knowledgeHitsJson)) {
            return List.of();
        }
        try {
            List<Map<String, Object>> items = objectMapper.readValue(
                    knowledgeHitsJson,
                    new TypeReference<List<Map<String, Object>>>() {}
            );
            return items.stream().map(this::toKnowledgeHitView).toList();
        } catch (Exception ignored) {
            return List.of();
        }
    }

    private KnowledgeHitView toKnowledgeHitView(Map<String, Object> item) {
        KnowledgeHitView view = new KnowledgeHitView();
        view.setSourceType(stringValue(item.get("source_type")));
        view.setSourceCode(stringValue(item.get("source_code")));
        view.setTitle(stringValue(item.get("title")));
        view.setSummary(stringValue(item.get("summary")));
        view.setSnippet(stringValue(item.get("snippet")));
        view.setScore(decimalValue(item.get("score")));
        view.setTags(stringList(item.get("tags")));
        Object metadata = item.get("metadata");
        if (metadata instanceof Map<?, ?> map) {
            java.util.LinkedHashMap<String, Object> normalized = new java.util.LinkedHashMap<>();
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                normalized.put(String.valueOf(entry.getKey()), entry.getValue());
            }
            view.setMetadata(normalized);
        }
        return view;
    }

    private Map<String, Object> parseKnowledgeTrace(String knowledgeTraceJson) {
        if (!StringUtils.hasText(knowledgeTraceJson)) {
            return null;
        }
        try {
            return objectMapper.readValue(knowledgeTraceJson, new TypeReference<Map<String, Object>>() {});
        } catch (Exception ignored) {
            return null;
        }
    }

    private BigDecimal decimalValue(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return new BigDecimal(String.valueOf(value));
        } catch (NumberFormatException exception) {
            return null;
        }
    }

    private String stringValue(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    private List<String> stringList(Object value) {
        if (!(value instanceof List<?> list)) {
            return List.of();
        }
        return list.stream().map(String::valueOf).toList();
    }

    private AgentGatewayDtos.AssistReplyResponse fetchAssistReply(
            ChatSession session,
            List<ChatMessage> messages,
            OrderInfo order,
            AfterSalesTicket ticket,
            String latestUserText
    ) {
        try {
            AgentGatewayDtos.ChatRequest request = new AgentGatewayDtos.ChatRequest();
            request.setSession_id(session.getId());
            if (session.getOrderId() != null) {
                request.setOrder_id(String.valueOf(session.getOrderId()));
            }
            request.setMessage(latestUserText);
            request.setDescription(firstNonBlank(
                    ticket == null ? null : ticket.getDescription(),
                    ticket == null ? null : ticket.getReasonDetail(),
                    latestUserText
            ));
            request.setSkip_image_review(true);
            request.setHuman_request_count(countHumanRequests(messages));
            request.setRecent_history(buildRecentHistoryDtos(messages));
            request.setSelected_order(buildSelectedOrderDto(session, order, ticket));
            return agentGatewayService.assistReply(request);
        } catch (Exception exception) {
            log.warn("Assist reply unavailable for session {}: {}", session.getId(), exception.getMessage());
            return null;
        }
    }

    private AgentGatewayDtos.KnowledgeRetrieveResponse fetchQuickReplyKnowledge(
            String latestUserText,
            OrderInfo order,
            String sceneCode,
            String intentCode
    ) {
        try {
            AgentGatewayDtos.KnowledgeRetrieveRequest request = new AgentGatewayDtos.KnowledgeRetrieveRequest();
            request.setQuery(latestUserText);
            request.setMerchantCode(currentMerchantCode());
            request.setProductCategory(resolveProductCategory(order));
            request.setScene(sceneCode);
            request.setIntent(intentCode);
            request.setTopK(6);
            request.setSources(List.of("reply_template"));
            return knowledgeRetrievalService.retrieve(request);
        } catch (Exception exception) {
            return null;
        }
    }

    private RecommendationView buildRecommendationView(
            AgentGatewayDtos.AssistReplyResponse assistReply,
            String latestUserText,
            String sceneCode
    ) {
        if (assistReply == null || !StringUtils.hasText(assistReply.getAssistant_reply())) {
            return null;
        }
        RecommendationView view = new RecommendationView();
        view.setText(assistReply.getAssistant_reply());
        view.setConfidence(normalizeConfidenceDecimal(assistReply.getReply_confidence()));
        view.setSource("售后 Agent · Qwen");
        view.setReason("基于用户对话上下文，由售后 Agent 生成可直接回复用户的话术。");
        view.setIntentCode(resolveAssistIntent(assistReply, assistReply.getAssistant_reply()));
        view.setSceneCode(sceneCode);
        view.setTone(readNestedString(assistReply.getEmotion(), "reply_tone", "clear"));
        return view;
    }

    private List<QuickReplyView> buildQuickReplyViews(AgentGatewayDtos.KnowledgeRetrieveResponse response) {
        if (response == null || response.getHits() == null || response.getHits().isEmpty()) {
            return List.of();
        }
        return response.getHits().stream().limit(6).map(hit -> {
            QuickReplyView view = new QuickReplyView();
            view.setCode(hit.getSource_code());
            view.setLabel(firstNonBlank(readMetadataString(hit, "description"), hit.getTitle(), hit.getSource_code(), "快捷回复"));
            view.setText(firstNonBlank(readMetadataString(hit, "template_text"), hit.getSnippet(), hit.getSummary(), ""));
            view.setSceneCode(readMetadataString(hit, "scene_code"));
            view.setIntentCode(readMetadataString(hit, "intent_code"));
            view.setTone(readMetadataString(hit, "tone"));
            view.setScore(normalizeScoreDecimal(hit.getScore()));
            return view;
        }).filter(item -> StringUtils.hasText(item.getText())).toList();
    }

    private QuickReplyView selectStaffSuggestion(AgentGatewayDtos.AssistReplyResponse assistReply) {
        String text = assistReply == null ? null : assistReply.getStaff_suggestion();
        if (!StringUtils.hasText(text)) {
            return null;
        }
        QuickReplyView view = new QuickReplyView();
        view.setCode("staff_suggestion");
        view.setLabel("上下文建议");
        view.setText(text.trim());
        view.setLabel("上下文建议");
        return view;
    }

    private Map<String, String> buildConversationDigest(
            ChatSession session,
            OrderInfo order,
            AfterSalesTicket ticket,
            List<ChatMessage> messages,
            AgentGatewayDtos.AssistReplyResponse assistReply,
            String intentCode,
            String sceneCode,
            RecommendationView recommendation
    ) {
        Map<String, Object> handoffSummary = assistReply == null ? null : assistReply.getHandoff_summary();
        Map<String, Object> raw = assistReply == null ? null : assistReply.getRaw();
        LinkedHashMap<String, String> digest = new LinkedHashMap<>();
        String resolvedIntent = firstNonBlank(
                assistReply == null ? null : assistReply.getIntent(),
                intentCode
        );
        String userNeed = buildDigestUserNeed(session, messages, handoffSummary, raw, resolvedIntent);
        String reason = buildDigestReason(session, messages, handoffSummary, raw);
        if (StringUtils.hasText(userNeed)) {
            digest.put("userNeed", userNeed.trim());
        }
        if (StringUtils.hasText(reason)) {
            digest.put("reason", reason.trim());
        }
        return digest;
    }

    private String buildDigestUserNeed(
            ChatSession session,
            List<ChatMessage> messages,
            Map<String, Object> handoffSummary,
            Map<String, Object> raw,
            String intentCode
    ) {
        String userNeed = readNestedString(raw, "conversation_understanding", "user_need");
        if (StringUtils.hasText(userNeed)) {
            return userNeed.trim();
        }
        if (handoffSummary != null && !handoffSummary.isEmpty()) {
            String problem = stringValue(handoffSummary.get("problem"));
            if (StringUtils.hasText(problem)) {
                return problem.trim();
            }
        }
        String mappedNeed = mapIntentToUserNeed(intentCode);
        if (StringUtils.hasText(mappedNeed)) {
            return mappedNeed;
        }
        List<String> userTexts = extractUserMessageTexts(messages);
        if (!userTexts.isEmpty()) {
            return userTexts.get(userTexts.size() - 1);
        }
        if (StringUtils.hasText(session.getUserQuery())) {
            return session.getUserQuery().trim();
        }
        return "";
    }

    private String buildDigestReason(
            ChatSession session,
            List<ChatMessage> messages,
            Map<String, Object> handoffSummary,
            Map<String, Object> raw
    ) {
        String normalizedIssue = readNestedString(raw, "conversation_understanding", "normalized_issue");
        if (StringUtils.hasText(normalizedIssue)) {
            return normalizedIssue.trim();
        }
        String understandingReason = readNestedString(raw, "conversation_understanding", "reason");
        if (StringUtils.hasText(understandingReason)) {
            return understandingReason.trim();
        }
        if (handoffSummary != null && !handoffSummary.isEmpty()) {
            String evidence = stringValue(handoffSummary.get("evidence"));
            if (StringUtils.hasText(evidence)) {
                return evidence.trim();
            }
        }
        List<String> userTexts = extractUserMessageTexts(messages);
        if (userTexts.size() >= 2) {
            return String.join("；", userTexts.subList(0, userTexts.size() - 1));
        }
        if (StringUtils.hasText(session.getUserQuery())) {
            return session.getUserQuery().trim();
        }
        return "";
    }

    private List<String> extractUserMessageTexts(List<ChatMessage> messages) {
        return messages.stream()
                .filter(message -> "USER".equalsIgnoreCase(message.getRole()))
                .map(ChatMessage::getContent)
                .filter(StringUtils::hasText)
                .map(String::trim)
                .toList();
    }

    private String mapIntentToUserNeed(String intentCode) {
        if (!StringUtils.hasText(intentCode)) {
            return "";
        }
        return switch (intentCode.trim()) {
            case "refund_only" -> "申请退款";
            case "refund_progress" -> "查询退款进度";
            case "return_logistics" -> "咨询退货物流";
            case "supplement_evidence" -> "补充售后凭证";
            case "merchant_rejected" -> "申诉商家驳回";
            case "exchange_repair" -> "申请换货或维修";
            case "human_service" -> "要求转人工客服";
            case "complaint" -> "投诉反馈";
            case "apply_after_sales" -> "申请售后处理";
            default -> "";
        };
    }

    private String formatConversationDigestText(Map<String, String> digest) {
        if (digest == null || digest.isEmpty()) {
            return null;
        }
        List<String> parts = new java.util.ArrayList<>();
        appendDigestPart(parts, "用户需求", digest.get("userNeed"));
        appendDigestPart(parts, "原因", digest.get("reason"));
        return parts.isEmpty() ? null : String.join("；", parts);
    }

    private void appendDigestPart(List<String> parts, String label, String value) {
        if (StringUtils.hasText(value)) {
            parts.add(label + "：" + value.trim());
        }
    }

    private String buildHandoffSummaryText(ChatSession session, Map<String, Object> handoffSummary) {
        if (handoffSummary != null && !handoffSummary.isEmpty()) {
            String problem = stringValue(handoffSummary.get("problem"));
            String suggestedAction = stringValue(handoffSummary.get("suggestedAction"));
            String userEmotion = stringValue(handoffSummary.get("userEmotion"));
            String evidence = stringValue(handoffSummary.get("evidence"));
            List<String> fragments = java.util.stream.Stream.of(problem, evidence, userEmotion, suggestedAction)
                    .filter(StringUtils::hasText)
                    .toList();
            if (!fragments.isEmpty()) {
                return String.join("；", fragments);
            }
            String summary = String.join("；", java.util.stream.Stream.of(problem, evidence, userEmotion, suggestedAction)
                    .filter(StringUtils::hasText)
                    .toList());
            if (StringUtils.hasText(summary)) {
                return summary;
            }
        }
        if (StringUtils.hasText(session.getUserQuery())) {
            return session.getUserQuery().trim();
        }
        return null;
    }

    private List<KnowledgeHitView> mapKnowledgeHits(List<AgentGatewayDtos.KnowledgeHitDto> hits) {
        if (hits == null || hits.isEmpty()) {
            return List.of();
        }
        return hits.stream().map(item -> {
            KnowledgeHitView view = new KnowledgeHitView();
            view.setSourceType(item.getSource_type());
            view.setSourceCode(item.getSource_code());
            view.setTitle(item.getTitle());
            view.setSummary(item.getSummary());
            view.setSnippet(item.getSnippet());
            view.setScore(normalizeScoreDecimal(item.getScore()));
            view.setTags(item.getTags());
            view.setMetadata(item.getMetadata());
            return view;
        }).toList();
    }

    private Map<String, Object> buildAssistTrace(
            AgentGatewayDtos.AssistReplyResponse assistReply,
            AgentGatewayDtos.KnowledgeRetrieveResponse quickReplyKnowledge
    ) {
        LinkedHashMap<String, Object> trace = new LinkedHashMap<>();
        if (assistReply != null && assistReply.getTrace() != null && !assistReply.getTrace().isEmpty()) {
            trace.put("assist_reply", assistReply.getTrace());
        }
        if (quickReplyKnowledge != null && quickReplyKnowledge.getTrace() != null && !quickReplyKnowledge.getTrace().isEmpty()) {
            trace.put("quick_reply_retrieval", quickReplyKnowledge.getTrace());
        }
        return trace.isEmpty() ? null : trace;
    }

    private AgentGatewayDtos.SelectedOrderDto buildSelectedOrderDto(
            ChatSession session,
            OrderInfo order,
            AfterSalesTicket ticket
    ) {
        AgentGatewayDtos.SelectedOrderDto dto = new AgentGatewayDtos.SelectedOrderDto();
        String orderRef = "";
        if (order != null) {
            orderRef = StringUtils.hasText(order.getOrderNo()) ? order.getOrderNo() : String.valueOf(order.getId());
        } else if (session.getOrderId() != null) {
            orderRef = String.valueOf(session.getOrderId());
        }
        dto.setOrder_id(orderRef);
        dto.setUser_id(String.valueOf(session.getUserId()));
        dto.setMerchant_code(session.getMerchantCode());
        dto.setProduct_name(resolveProductName(order, ticket));
        dto.setCategory(resolveProductCategory(order));
        dto.setStatus(toAgentOrderStatus(order == null ? null : order.getStatus()));
        dto.setAfter_sales_status(toAgentAfterSalesStatus(ticket));
        dto.setAmount(order != null && order.getPayAmount() != null ? order.getPayAmount().doubleValue() : null);
        dto.setRefund_status(ticket == null || ticket.getStatus() == null ? "" : ticket.getStatus());
        dto.setLogistics_status(order == null ? "" : logisticsStatus(order));
        dto.setHas_open_after_sales(ticket != null);
        dto.setUploaded_evidence(loadTicketEvidence(ticket == null ? null : ticket.getId()));
        dto.setMerchant_rejected_before(ticket != null && "REJECTED".equalsIgnoreCase(ticket.getStatus()));
        return dto;
    }

    private List<AgentGatewayDtos.ConversationMessageDto> buildRecentHistoryDtos(List<ChatMessage> messages) {
        if (messages == null || messages.isEmpty()) {
            return List.of();
        }
        int fromIndex = Math.max(messages.size() - 12, 0);
        return messages.subList(fromIndex, messages.size()).stream().map(message -> {
            AgentGatewayDtos.ConversationMessageDto item = new AgentGatewayDtos.ConversationMessageDto();
            item.setRole("USER".equalsIgnoreCase(message.getRole()) ? "user" : "service");
            item.setContent(message.getContent());
            return item;
        }).toList();
    }

    private ChatMessage latestUserMessage(List<ChatMessage> messages) {
        for (int index = messages.size() - 1; index >= 0; index--) {
            ChatMessage message = messages.get(index);
            if ("USER".equalsIgnoreCase(message.getRole()) && StringUtils.hasText(message.getContent())) {
                return message;
            }
        }
        return null;
    }

    private int countHumanRequests(List<ChatMessage> messages) {
        int count = 0;
        for (ChatMessage message : messages) {
            if (!"USER".equalsIgnoreCase(message.getRole())) {
                continue;
            }
            String content = Optional.ofNullable(message.getContent()).orElse("");
            if (containsKeyword(content, "人工", "真人", "客服", "投诉")) {
                count++;
            }
        }
        return count;
    }

    private String resolveAssistIntent(AgentGatewayDtos.AssistReplyResponse assistReply, String latestUserText) {
        if (assistReply != null && StringUtils.hasText(assistReply.getIntent())) {
            return assistReply.getIntent();
        }
        String normalized = Optional.ofNullable(latestUserText).orElse("");
        if (containsKeyword(normalized, "退款进度", "多久到账", "什么时候退款", "退款到了吗")) {
            return "refund_progress";
        }
        if (containsKeyword(normalized, "补发", "少发", "漏发", "缺件")) {
            return "apply_after_sales";
        }
        if (containsKeyword(normalized, "退货", "退款", "售后")) {
            return "apply_after_sales";
        }
        return "general";
    }

    private String resolveAssistScene(
            AgentGatewayDtos.AssistReplyResponse assistReply,
            String latestUserText,
            AfterSalesTicket ticket
    ) {
        String scene = readNestedString(assistReply == null ? null : assistReply.getRaw(), "conversation_understanding", "scene");
        if (StringUtils.hasText(scene)) {
            return scene;
        }
        if (ticket != null && StringUtils.hasText(ticket.getReason())) {
            String mapped = mapTicketReasonToScene(ticket.getReason());
            if (StringUtils.hasText(mapped)) {
                return mapped;
            }
        }
        String normalized = Optional.ofNullable(latestUserText).orElse("");
        if (containsKeyword(normalized, "少发", "漏发", "缺件", "补发")) {
            return "wrong_or_missing_items";
        }
        if (containsKeyword(normalized, "物流", "快递", "发货", "签收")) {
            return "logistics_issue";
        }
        if (containsKeyword(normalized, "没声音", "故障", "坏了", "质量", "损坏", "异常")) {
            return "quality_issue";
        }
        if (containsKeyword(normalized, "退款进度", "多久到账")) {
            return "progress_query";
        }
        return "general";
    }

    private String buildRecommendationReason(AgentGatewayDtos.AssistReplyResponse assistReply, String sceneCode) {
        String mode = readNestedString(assistReply == null ? null : assistReply.getRaw(), "mode");
        if (mode.contains("knowledge_short_circuit")) {
            return "命中知识库说明型答案，优先给出可直接发送的话术。";
        }
        if (StringUtils.hasText(assistReply == null ? null : assistReply.getKnowledge_retrieval_mode())) {
            return "结合当前会话、知识检索结果和规则链生成推荐回复。";
        }
        if ("quality_issue".equals(sceneCode)) {
            return "识别到质量/故障场景，优先生成安抚和补充信息类回复。";
        }
        if ("wrong_or_missing_items".equals(sceneCode)) {
            return "识别到少发漏发场景，优先生成补发核验类回复。";
        }
        return "根据当前会话上下文生成推荐回复。";
    }

    private String resolveProductName(OrderInfo order, AfterSalesTicket ticket) {
        if (ticket != null && StringUtils.hasText(ticket.getProductName())) {
            return ticket.getProductName();
        }
        List<OrderItem> items = order == null ? List.of() : orderItemMapper.selectList(new LambdaQueryWrapper<OrderItem>()
                .eq(OrderItem::getOrderId, order.getId())
                .orderByAsc(OrderItem::getId));
        if (!items.isEmpty()) {
            ProductInfo product = productInfoMapper.selectById(items.get(0).getProductId());
            if (product != null && StringUtils.hasText(product.getProductName())) {
                return product.getProductName();
            }
        }
        return "";
    }

    private String resolveProductCategory(OrderInfo order) {
        if (order == null) {
            return "";
        }
        List<OrderItem> items = orderItemMapper.selectList(new LambdaQueryWrapper<OrderItem>()
                .eq(OrderItem::getOrderId, order.getId())
                .orderByAsc(OrderItem::getId));
        if (items.isEmpty()) {
            return "";
        }
        ProductInfo product = productInfoMapper.selectById(items.get(0).getProductId());
        return product == null ? "" : Optional.ofNullable(product.getCategory()).orElse("");
    }

    private List<String> loadTicketEvidence(Long ticketId) {
        if (ticketId == null) {
            return List.of();
        }
        return ticketAttachmentMapper.selectList(new LambdaQueryWrapper<TicketAttachment>()
                        .eq(TicketAttachment::getTicketId, ticketId)
                        .orderByAsc(TicketAttachment::getSortOrder)
                        .orderByAsc(TicketAttachment::getId))
                .stream()
                .map(item -> firstNonBlank(item.getFileName(), item.getFileType(), item.getFileUrl()))
                .filter(StringUtils::hasText)
                .toList();
    }

    private String toAgentOrderStatus(String status) {
        return switch (Optional.ofNullable(status).orElse("")) {
            case "PAID" -> "paid";
            case "SHIPPED" -> "shipped";
            case "DELIVERED" -> "delivered";
            case "COMPLETED" -> "completed";
            case "REFUNDED" -> "refunded";
            default -> "paid";
        };
    }

    private String toAgentAfterSalesStatus(AfterSalesTicket ticket) {
        if (ticket == null || !StringUtils.hasText(ticket.getStatus())) {
            return "not_applied";
        }
        return switch (ticket.getStatus().toUpperCase()) {
            case "PENDING", "PENDING_REVIEW" -> "submitted";
            case "PROCESSING" -> "merchant_review";
            case "APPROVED" -> "approved";
            case "REJECTED" -> "rejected";
            case "COMPLETED" -> "completed";
            case "CLOSED" -> "closed";
            default -> "not_applied";
        };
    }

    private String mapTicketReasonToScene(String reason) {
        if (!StringUtils.hasText(reason)) {
            return "";
        }
        String normalized = reason.toLowerCase();
        if (normalized.contains("missing") || normalized.contains("wrong")) {
            return "wrong_or_missing_items";
        }
        if (normalized.contains("damage")) {
            return "product_damage";
        }
        if (normalized.contains("logistics")) {
            return "logistics_issue";
        }
        if (normalized.contains("quality")) {
            return "quality_issue";
        }
        return "";
    }

    private boolean containsKeyword(String text, String... keywords) {
        if (!StringUtils.hasText(text)) {
            return false;
        }
        for (String keyword : keywords) {
            if (StringUtils.hasText(keyword) && text.contains(keyword)) {
                return true;
            }
        }
        return false;
    }

    private String firstNonBlank(String... values) {
        for (String value : values) {
            if (StringUtils.hasText(value)) {
                return value;
            }
        }
        return "";
    }

    private String readMetadataString(AgentGatewayDtos.KnowledgeHitDto hit, String key) {
        if (hit == null || hit.getMetadata() == null) {
            return "";
        }
        Object value = hit.getMetadata().get(key);
        return value == null ? "" : String.valueOf(value);
    }

    private String readNestedString(Map<String, Object> source, String key) {
        if (source == null) {
            return "";
        }
        Object value = source.get(key);
        return value == null ? "" : String.valueOf(value);
    }

    @SuppressWarnings("unchecked")
    private String readNestedString(Map<String, Object> source, String parentKey, String childKey) {
        if (source == null) {
            return "";
        }
        Object parent = source.get(parentKey);
        if (!(parent instanceof Map<?, ?> map)) {
            return "";
        }
        Object value = ((Map<String, Object>) map).get(childKey);
        return value == null ? "" : String.valueOf(value);
    }

    private BigDecimal normalizeConfidenceDecimal(Double value) {
        if (value == null) {
            return null;
        }
        double numeric = value > 1 ? value / 100.0 : value;
        numeric = Math.max(0.0, Math.min(1.0, numeric));
        return BigDecimal.valueOf(numeric).setScale(2, java.math.RoundingMode.HALF_UP);
    }

    private BigDecimal normalizeScoreDecimal(Double value) {
        if (value == null) {
            return null;
        }
        double numeric = Math.max(0.0, value);
        if (numeric > 1.0) {
            numeric = numeric / 100.0;
        }
        return BigDecimal.valueOf(Math.min(1.0, numeric)).setScale(2, java.math.RoundingMode.HALF_UP);
    }

    private List<TicketView> allTickets() {
        return afterSalesTicketMapper.selectList(new LambdaQueryWrapper<AfterSalesTicket>()
                        .eq(AfterSalesTicket::getMerchantCode, currentMerchantCode())
                        .orderByDesc(AfterSalesTicket::getCreateTime))
                .stream()
                .map(this::toTicketView)
                .toList();
    }

    private TicketView toTicketView(AfterSalesTicket ticket) {
        TicketView view = new TicketView();
        view.setId(ticket.getId());
        view.setTicketNo(ticket.getTicketNo());
        view.setMerchantCode(ticket.getMerchantCode());
        view.setOrderId(ticket.getOrderId());
        view.setOrderNo(ticket.getOrderNo());
        view.setUserId(ticket.getUserId());
        view.setTitle(Optional.ofNullable(ticket.getProductName()).orElse("售后申请"));
        view.setStatus(toMerchantTicketStatus(ticket.getStatus()));
        view.setAfterSalesType(toMerchantAfterSalesType(Optional.ofNullable(ticket.getAfterSaleType()).orElse(ticket.getAiRecommendType())));
        view.setReasonType(ticket.getReason());
        view.setApplyRefundAmount(money(ticket.getRefundAmount()));
        view.setApprovedRefundAmount("PROCESSING".equals(ticket.getStatus()) || "COMPLETED".equals(ticket.getStatus()) ? money(ticket.getRefundAmount()) : null);
        view.setRefundStatus("COMPLETED".equals(ticket.getStatus()) ? "SUCCESS" : "PENDING");
        view.setAiConfidence(ticket.getAiConfidence());
        view.setPriority(toPriorityText(ticket.getPriority()));
        view.setResponsibility("MERCHANT");
        view.setAssignedServiceId(ticket.getAssigneeId());
        view.setAuditOpinion(ticket.getAuditOpinion());
        view.setRejectReason("REJECTED".equals(ticket.getStatus()) ? ticket.getAuditOpinion() : null);
        view.setExpectedFinishTime(format(ticket.getExpectedCompleteTime()));
        view.setAuditTime(format(ticket.getAuditTime()));
        view.setCompleteTime(format(ticket.getCompleteTime()));
        return view;
    }

    private TicketLogView toTicketLogView(TicketLog log) {
        TicketLogView view = new TicketLogView();
        view.setId(log.getId());
        view.setTicketId(log.getTicketId());
        view.setOperatorId(log.getOperatorId());
        view.setOperatorRole(log.getOperatorType());
        view.setOldStatus(toMerchantTicketStatus(log.getFromStatus()));
        view.setNewStatus(toMerchantTicketStatus(log.getToStatus()));
        view.setActionType(log.getAction());
        view.setActionDesc(log.getContent());
        view.setCreatedAt(format(log.getCreateTime()));
        return view;
    }

    private OrderView toOrderView(OrderInfo order) {
        User user = userMapper.selectById(order.getUserId());
        OrderView view = new OrderView();
        view.setId(order.getId());
        view.setOrderNo(order.getOrderNo());
        view.setMerchantCode(order.getMerchantCode());
        view.setUserId(order.getUserId());
        view.setUser(userDisplayName(user));
        view.setPhone(maskPhone(order.getReceiverPhone()));
        view.setProduct(orderItems(order.getId()).stream().map(OrderProductItem::getProductName).collect(Collectors.joining("、")));
        view.setAmount(money(order.getPayAmount()));
        view.setStatus(order.getStatus());
        view.setLogistics(logisticsStatus(order));
        view.setRelatedTicketId(findTicketByOrderId(order.getId()).map(AfterSalesTicket::getId).orElse(null));
        view.setCreatedAt(format(order.getCreateTime()));
        return view;
    }

    private List<OrderProductItem> orderItems(Long orderId) {
        return orderItemMapper.selectList(new LambdaQueryWrapper<OrderItem>().eq(OrderItem::getOrderId, orderId))
                .stream()
                .map(item -> {
                    ProductInfo product = productInfoMapper.selectById(item.getProductId());
                    OrderProductItem view = new OrderProductItem();
                    view.setProductId(item.getProductId());
                    view.setProductName(product == null ? "未知商品" : product.getProductName());
                    view.setQuantity(item.getQuantity());
                    view.setPrice(money(item.getPrice()));
                    return view;
                })
                .toList();
    }

    private NoticeView toNoticeView(MessageNotice notice) {
        NoticeView view = new NoticeView();
        view.setId(notice.getId());
        view.setLevel(noticeLevel(notice.getNoticeType()));
        view.setTitle(notice.getTitle());
        view.setContent(notice.getContent());
        view.setTarget(noticeTarget(notice));
        view.setReadStatus(Integer.valueOf(1).equals(notice.getIsRead()) ? "READ" : "UNREAD");
        view.setCreatedAt(format(notice.getCreateTime()));
        return view;
    }

    private ProductView toProductView(ProductInfo product) {
        ProductView view = new ProductView();
        view.setId(product.getId());
        view.setMerchantCode(product.getMerchantCode());
        view.setProductName(product.getProductName());
        view.setProductCode(product.getProductCode());
        view.setCategory(product.getCategory());
        view.setDescription(product.getDescription());
        view.setMainImage(product.getMainImage());
        view.setImages(parseImages(product.getImages()));
        view.setPrice(product.getPrice());
        view.setStatus(Integer.valueOf(1).equals(product.getStatus()) ? "ON_SALE" : "OFF_SALE");
        view.setCreatedAt(format(product.getCreateTime()));
        view.setUpdatedAt(format(product.getUpdateTime()));
        return view;
    }

    private void applyProductRequest(ProductInfo product, ProductUpsertRequest request) {
        if (!StringUtils.hasText(request.getProductName())) {
            throw new BizException("商品名称不能为空");
        }
        if (request.getPrice() == null || request.getPrice().compareTo(BigDecimal.ZERO) < 0) {
            throw new BizException("商品价格不能小于 0");
        }
        product.setProductName(request.getProductName());
        product.setProductCode(request.getProductCode());
        product.setCategory(request.getCategory());
        product.setDescription(request.getDescription());
        product.setMainImage(request.getMainImage());
        product.setImages(writeImages(request.getImages()));
        product.setPrice(request.getPrice());
        product.setStatus(toProductStatusValue(request.getStatus()));
    }

    private void addSystemMessage(Long sessionId, String content) {
        ChatMessage message = new ChatMessage();
        message.setSessionId(sessionId);
        message.setRole("SYSTEM");
        message.setMessageType("TEXT");
        message.setContent(content);
        chatMessageMapper.insert(message);
    }

    private void markRelatedSessionsReadyForEvaluation(AfterSalesTicket ticket) {
        List<ChatSession> sessions = chatSessionMapper.selectList(new LambdaQueryWrapper<ChatSession>()
                .eq(ChatSession::getMerchantCode, currentMerchantCode())
                .eq(ChatSession::getMode, "HUMAN")
                .eq(ChatSession::getTicketId, ticket.getId())
                .ne(ChatSession::getStatus, "CLOSED"));
        for (ChatSession session : sessions) {
            session.setStatus("PROCESSING");
            session.setResolved(0);
            session.setHumanAgentId(ensureStaff().getId());
            chatSessionMapper.updateById(session);
            addSystemMessage(session.getId(), "售后处理已完成，客服可以发送服务评价请求。");
        }
    }

    private void addTicketLog(AfterSalesTicket ticket, String oldStatus, String newStatus, String action, String content) {
        TicketLog log = new TicketLog();
        log.setTicketId(ticket.getId());
        log.setOperatorId(ensureStaff().getId());
        log.setOperatorType("AGENT");
        log.setFromStatus(oldStatus);
        log.setToStatus(newStatus);
        log.setAction(action);
        log.setContent(content);
        ticketLogMapper.insert(log);
    }

    private ChatSession findSession(Long sessionId) {
        ChatSession session = chatSessionMapper.selectById(sessionId);
        if (session == null) {
            throw new BizException(404, "会话不存在");
        }
        assertCurrentMerchant(session.getMerchantCode(), "会话不存在");
        if (!"HUMAN".equals(session.getMode())) {
            throw new BizException(404, "会话不存在");
        }
        return session;
    }

    private AfterSalesTicket findTicket(Long ticketId) {
        AfterSalesTicket ticket = afterSalesTicketMapper.selectById(ticketId);
        if (ticket == null) {
            throw new BizException(404, "售后申请不存在");
        }
        assertCurrentMerchant(ticket.getMerchantCode(), "售后申请不存在");
        return ticket;
    }

    private OrderInfo findOrder(Long orderId) {
        OrderInfo order = orderInfoMapper.selectById(orderId);
        if (order == null) {
            throw new BizException(404, "订单不存在");
        }
        assertCurrentMerchant(order.getMerchantCode(), "订单不存在");
        return order;
    }

    private ProductInfo findProduct(Long productId) {
        ProductInfo product = productInfoMapper.selectById(productId);
        if (product == null) {
            throw new BizException(404, "商品不存在");
        }
        assertCurrentMerchant(product.getMerchantCode(), "商品不存在");
        return product;
    }

    private Optional<AfterSalesTicket> findTicketByOrderId(Long orderId) {
        return Optional.ofNullable(afterSalesTicketMapper.selectOne(new LambdaQueryWrapper<AfterSalesTicket>()
                .eq(AfterSalesTicket::getOrderId, orderId)
                .eq(AfterSalesTicket::getMerchantCode, currentMerchantCode())
                .orderByDesc(AfterSalesTicket::getCreateTime)
                .last("limit 1")));
    }

    private Long currentStaffId() {
        ServletRequestAttributes attributes = (ServletRequestAttributes) RequestContextHolder.getRequestAttributes();
        if (attributes == null) {
            return null;
        }
        String authorization = attributes.getRequest().getHeader("Authorization");
        if (!StringUtils.hasText(authorization) || !authorization.startsWith("Bearer ")) {
            return null;
        }
        return jwtTokenUtil.parseUserIdOrNull(authorization.substring("Bearer ".length()));
    }

    private String currentMerchantCode() {
        return merchantCodeOf(ensureStaff());
    }

    private String merchantCodeOf(SysUser staff) {
        return normalizeMerchantCode(staff == null ? null : staff.getMerchantCode());
    }

    private String normalizeMerchantCode(String merchantCode) {
        return StringUtils.hasText(merchantCode) ? merchantCode.trim() : DEFAULT_MERCHANT_CODE;
    }

    private String buildAutoMerchantCode(Long staffId) {
        return staffId == null ? DEFAULT_MERCHANT_CODE : "MERCHANT_" + staffId;
    }

    private String normalizePhone(String phone) {
        return StringUtils.hasText(phone) ? phone.trim() : "";
    }

    private String normalizeAuthScene(String scene) {
        String normalized = StringUtils.hasText(scene) ? scene.trim().toUpperCase() : "";
        if (REGISTER_SCENE.equals(normalized) || RESET_PASSWORD_SCENE.equals(normalized)) {
            return normalized;
        }
        throw new BizException("验证码场景不支持");
    }

    private void assertCurrentMerchant(String merchantCode, String notFoundMessage) {
        if (!currentMerchantCode().equals(normalizeMerchantCode(merchantCode))) {
            throw new BizException(404, notFoundMessage);
        }
    }

    private List<TimelineItem> buildTimeline() {
        List<TimelineItem> items = new ArrayList<>();
        allTickets().stream().limit(3).forEach(ticket -> {
            TimelineItem item = new TimelineItem();
            item.setTime(Optional.ofNullable(ticket.getAuditTime()).orElse(""));
            item.setTitle("申请 " + ticket.getTicketNo() + " 当前状态：" + ticket.getStatus());
            item.setType("HIGH".equals(ticket.getPriority()) ? "warn" : "normal");
            items.add(item);
        });
        if (items.isEmpty()) {
            TimelineItem item = new TimelineItem();
            item.setTime(LocalDateTime.now().format(DateTimeFormatter.ofPattern("HH:mm")));
            item.setTitle("暂无新的客服任务");
            item.setType("normal");
            items.add(item);
        }
        return items;
    }

    private MetricItem metric(String title, Object value, String trend, String accent) {
        MetricItem metric = new MetricItem();
        metric.setTitle(title);
        metric.setValue(value);
        metric.setTrend(trend);
        metric.setAccent(accent);
        return metric;
    }

    private PerformanceMetric performanceMetric(String label, String value, String desc, Integer current, Integer target) {
        PerformanceMetric metric = new PerformanceMetric();
        metric.setLabel(label);
        metric.setValue(value);
        metric.setDesc(desc);
        metric.setCurrentPercent(current);
        metric.setTargetPercent(target);
        return metric;
    }

    private boolean containsAny(String keyword, String... values) {
        return Arrays.stream(values).filter(Objects::nonNull).anyMatch(value -> value.contains(keyword));
    }

    private String format(LocalDateTime value) {
        return value == null ? null : DATE_TIME_FORMATTER.format(value);
    }

    private String money(BigDecimal value) {
        return value == null ? "0.00" : value.setScale(2).toPlainString();
    }

    private String userDisplayName(User user) {
        if (user == null) {
            return "未知用户";
        }
        return StringUtils.hasText(user.getNickname()) ? user.getNickname() : user.getUserAccount();
    }

    private String maskPhone(String phone) {
        if (!StringUtils.hasText(phone) || phone.length() < 7) {
            return phone;
        }
        return phone.substring(0, 3) + "****" + phone.substring(phone.length() - 4);
    }

    private String waitText(LocalDateTime createTime) {
        if (createTime == null) {
            return "等待中";
        }
        long minutes = Math.max(Duration.between(createTime, LocalDateTime.now()).toMinutes(), 0);
        return "等待 " + String.format("%02d:%02d", minutes / 60, minutes % 60);
    }

    private String emotionText(String emotionLabel) {
        return switch (normalizeEmotionLabel(emotionLabel)) {
            case "SATISFIED" -> "满意";
            case "ANGRY" -> "情绪预警";
            case "ANXIOUS", "ANXIETY" -> "焦急";
            case "DISSATISFIED" -> "不满";
            default -> "中性";
        };
    }

    private String normalizeEmotionLabel(String emotionLabel) {
        String normalized = Optional.ofNullable(emotionLabel).orElse("CALM").trim().toUpperCase();
        return switch (normalized) {
            case "", "NORMAL", "NEUTRAL" -> "CALM";
            case "ANXIETY" -> "ANXIOUS";
            default -> normalized;
        };
    }
    private String priorityLabel(AfterSalesTicket ticket) {
        if (ticket == null) {
            return "普通优先级";
        }
        return ticket.getPriority() != null && ticket.getPriority() > 0 ? "高优先级" : "普通优先级";
    }

    private String toPriorityText(Integer priority) {
        return priority != null && priority > 0 ? "HIGH" : "NORMAL";
    }

    private String logisticsStatus(OrderInfo order) {
        if (StringUtils.hasText(order.getTrackingNo())) {
            return order.getReceiveTime() == null ? "运输中" : "已签收";
        }
        return "待发货";
    }

    private String toMerchantSessionStatus(ChatSession session) {
        if ("CLOSED".equals(session.getStatus())) {
            return "CLOSED";
        }
        if ("AWAITING_EVALUATION".equals(session.getStatus()) && isEvaluationExpired(session)) {
            return "READY_TO_CLOSE";
        }
        if ("READY_TO_CLOSE".equals(session.getStatus())) {
            return "READY_TO_CLOSE";
        }
        if (Integer.valueOf(1).equals(session.getResolved())) {
            return "READY_TO_CLOSE";
        }
        return switch (Optional.ofNullable(session.getStatus()).orElse("ACTIVE")) {
            case "WAITING" -> "WAITING";
            case "AWAITING_EVALUATION" -> "AWAITING_EVALUATION";
            case "CLOSED" -> "CLOSED";
            default -> "PROCESSING";
        };
    }

    private boolean canCloseSession(ChatSession session) {
        return "READY_TO_CLOSE".equals(session.getStatus())
                || Integer.valueOf(1).equals(session.getResolved())
                || ("AWAITING_EVALUATION".equals(session.getStatus()) && isEvaluationExpired(session));
    }

    private boolean isEvaluationExpired(ChatSession session) {
        return session.getUpdateTime() != null
                && Duration.between(session.getUpdateTime(), LocalDateTime.now()).compareTo(EVALUATION_TIMEOUT) >= 0;
    }

    private String evaluationStatus(ChatSession session) {
        if (session.getSatisfaction() != null) {
            return "SUBMITTED";
        }
        if ("AWAITING_EVALUATION".equals(session.getStatus()) && isEvaluationExpired(session)) {
            return "TIMEOUT";
        }
        if ("AWAITING_EVALUATION".equals(session.getStatus())) {
            return "PENDING";
        }
        return null;
    }

    private String toMerchantTicketStatus(String status) {
        if (status == null) {
            return null;
        }
        return switch (status) {
            case "PENDING" -> "PENDING_REVIEW";
            default -> status;
        };
    }

    private String toMerchantAfterSalesType(String type) {
        if (type == null) {
            return "REFUND_ONLY";
        }
        return switch (type) {
            case "REFUND", "REFUND_ONLY" -> "REFUND_ONLY";
            case "RETURN", "REFUND_RETURN", "RETURN_REFUND", "REPAIR" -> "RETURN_REFUND";
            case "RESEND", "REISSUE", "EXCHANGE" -> "REISSUE";
            case "PARTIAL_REFUND" -> "PARTIAL_REFUND";
            default -> type;
        };
    }

    private Integer toOnlineStatusValue(String status) {
        return switch (Optional.ofNullable(status).orElse("ONLINE")) {
            case "OFFLINE" -> 0;
            case "BUSY" -> 2;
            default -> 1;
        };
    }

    private String toOnlineStatusText(Integer status) {
        return switch (Optional.ofNullable(status).orElse(0)) {
            case 1 -> "ONLINE";
            case 2 -> "BUSY";
            default -> "OFFLINE";
        };
    }

    private Integer toProductStatusValue(String status) {
        return "OFF_SALE".equals(status) ? 0 : 1;
    }

    private String noticeLevel(String noticeType) {
        return "AFTER_SALE".equals(noticeType) || "CHAT".equals(noticeType) ? "HIGH" : "NORMAL";
    }

    private String noticeTarget(MessageNotice notice) {
        if ("TICKET".equals(notice.getRefType())) {
            return "/tickets/" + notice.getRefId();
        }
        if ("ORDER".equals(notice.getRefType())) {
            return "/orders/" + notice.getRefId();
        }
        return "/notices";
    }

    private List<String> parseImages(String images) {
        if (!StringUtils.hasText(images)) {
            return Collections.emptyList();
        }
        try {
            return objectMapper.readValue(images, new TypeReference<>() {
            });
        } catch (Exception exception) {
            return List.of(images);
        }
    }

    private String writeImages(List<String> images) {
        if (images == null || images.isEmpty()) {
            return "[]";
        }
        try {
            return objectMapper.writeValueAsString(images);
        } catch (Exception exception) {
            throw new BizException("商品图片格式错误");
        }
    }
}

