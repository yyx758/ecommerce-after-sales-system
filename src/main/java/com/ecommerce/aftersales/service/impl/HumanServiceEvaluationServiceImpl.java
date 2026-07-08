package com.ecommerce.aftersales.service.impl;

import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.dto.HumanServiceEvaluationDtos.*;
import com.ecommerce.aftersales.service.HumanServiceEvaluationService;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

@Service
public class HumanServiceEvaluationServiceImpl implements HumanServiceEvaluationService {

    private static final DateTimeFormatter TIME_FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final AtomicLong idGenerator = new AtomicLong(5000L);
    private final Map<Long, EvaluationDetailResponse> evaluationsById = new LinkedHashMap<>();
    private final Map<Long, Long> evaluationIdBySessionId = new LinkedHashMap<>();

    @Override
    public MetricDesignResponse getMetricDesign() {
        MetricDesignResponse response = new MetricDesignResponse();
        response.setVersion("v1");
        response.setScope("human_customer_service_only");
        response.setCategories(List.of(
                buildCategory("result", "Result Layer", 45, List.of(
                        metric("human_csat", "Human CSAT", 20,
                                "Measure post-service satisfaction for the assigned human agent.",
                                "rating_overall / 5 * 100", "user"),
                        metric("resolution_rate", "Resolution Rate", 15,
                                "Check whether the issue is actually resolved after human intervention.",
                                "resolved_flag and no repeat issue within short window", "system"),
                        metric("reopen_rate", "Reopen Rate", 10,
                                "Penalize cases reopened within 7 days after manual service.",
                                "1 - reopened_7d_rate", "system")
                )),
                buildCategory("process", "Process Layer", 25, List.of(
                        metric("first_human_response", "First Human Response", 10,
                                "Measure the speed from assignment to the first human response.",
                                "bucket(first_human_response_seconds)", "system"),
                        metric("fcr", "First Contact Resolution", 10,
                                "Check whether human service resolves the issue without another manual round.",
                                "first_contact_resolved_flag", "system"),
                        metric("sla", "SLA Compliance", 5,
                                "Check whether promised service timing is met.", "sla_met_flag", "system")
                )),
                buildCategory("quality", "Quality Layer", 20, List.of(
                        metric("attitude", "Service Attitude", 5,
                                "Measure politeness and emotional care.", "rating_attitude and qa_attitude_score", "user+qa"),
                        metric("professional", "Professional Accuracy", 7,
                                "Measure whether explanation and policy guidance are correct.",
                                "rating_professional and qaProfessionalScore", "user+qa"),
                        metric("guidance", "Process Guidance", 4,
                                "Measure whether materials and next steps are clearly explained.",
                                "rating_efficiency and qaProcessScore", "user+qa"),
                        metric("closure", "Closure Ownership", 4,
                                "Measure whether service provides clear closure and follow-up responsibility.",
                                "rating_resolution and qaClosureScore", "user+qa")
                )),
                buildCategory("emotion", "Emotion Layer", 10, List.of(
                        metric("emotion_relief", "Emotion Relief", 6,
                                "Measure whether user emotion de-escalates during human service.",
                                "emotion_before_human -> emotion_after_human", "system"),
                        metric("high_risk_relief", "High Risk Relief", 4,
                                "Check whether high-risk conversations calm down without escalation or repeat contact.",
                                "high risk relief success rate", "system")
                ))
        ));
        response.setNotes(List.of(
                "Only evaluate conversations that are actually handled by a human agent.",
                "Do not use NPS as a direct individual KPI for a single agent.",
                "Emotion metrics are supporting indicators and should not dominate the final score.",
                "Logistics and warehouse root causes should be separated from directly controllable service quality."
        ));
        return response;
    }

    @Override
    public synchronized EvaluationDetailResponse submitEvaluation(SubmitEvaluationRequest request) {
        Long existingId = evaluationIdBySessionId.get(request.getSessionId());
        EvaluationDetailResponse detail = existingId == null
                ? new EvaluationDetailResponse()
                : copy(evaluationsById.get(existingId));
        if (detail.getEvaluationId() == null) {
            detail.setEvaluationId(idGenerator.incrementAndGet());
            detail.setCreatedAt(now());
        }
        detail.setSessionId(request.getSessionId());
        detail.setHumanAgentId(request.getHumanAgentId());
        detail.setUserId(request.getUserId());
        detail.setMerchantCode(request.getMerchantCode());
        detail.setStatus("USER_SUBMITTED");
        detail.setRatingOverall(request.getRatingOverall());
        detail.setRatingAttitude(request.getRatingAttitude());
        detail.setRatingProfessional(request.getRatingProfessional());
        detail.setRatingEfficiency(request.getRatingEfficiency());
        detail.setRatingResolution(request.getRatingResolution());
        detail.setCesScore(request.getCesScore());
        detail.setResolvedFlag(defaultFalse(request.getResolvedFlag()));
        detail.setFirstContactResolvedFlag(defaultFalse(request.getFirstContactResolvedFlag()));
        detail.setSlaMetFlag(defaultFalse(request.getSlaMetFlag()));
        detail.setFirstHumanResponseSeconds(request.getFirstHumanResponseSeconds());
        detail.setComment(request.getComment());
        detail.setEmotionBeforeHuman(normalizeEmotion(request.getEmotionBeforeHuman()));
        detail.setEmotionAfterHuman(normalizeEmotion(request.getEmotionAfterHuman()));
        detail.setEmotionDelta(calculateEmotionDelta(detail.getEmotionBeforeHuman(), detail.getEmotionAfterHuman()));
        detail.setRecontact72h(defaultFalse(request.getRecontact72h()));
        detail.setReopened7d(defaultFalse(request.getReopened7d()));
        applyScores(detail);
        detail.setUpdatedAt(now());

        evaluationsById.put(detail.getEvaluationId(), copy(detail));
        evaluationIdBySessionId.put(detail.getSessionId(), detail.getEvaluationId());
        return detail;
    }

    @Override
    public synchronized EvaluationDetailResponse getEvaluationBySessionId(Long sessionId) {
        Long evaluationId = evaluationIdBySessionId.get(sessionId);
        if (evaluationId == null) {
            throw new BizException(404, "Evaluation record not found for session");
        }
        return copy(evaluationsById.get(evaluationId));
    }

    @Override
    public synchronized EvaluationDetailResponse submitQaReview(Long evaluationId, QaReviewRequest request) {
        EvaluationDetailResponse detail = evaluationsById.get(evaluationId);
        if (detail == null) {
            throw new BizException(404, "Evaluation record not found");
        }
        EvaluationDetailResponse editable = copy(detail);
        editable.setQaAttitudeScore(request.getQaAttitudeScore());
        editable.setQaProfessionalScore(request.getQaProfessionalScore());
        editable.setQaProcessScore(request.getQaProcessScore());
        editable.setQaClosureScore(request.getQaClosureScore());
        editable.setQaComment(request.getQaComment());
        editable.setReviewerName(request.getReviewerName());
        editable.setStatus("QA_REVIEWED");
        applyScores(editable);
        editable.setUpdatedAt(now());

        evaluationsById.put(evaluationId, copy(editable));
        return editable;
    }

    @Override
    public synchronized AgentPerformanceOverviewResponse getAgentOverview(Long agentId, LocalDate from, LocalDate to) {
        LocalDate statFrom = from == null ? LocalDate.now().minusDays(29) : from;
        LocalDate statTo = to == null ? LocalDate.now() : to;
        List<EvaluationDetailResponse> agentRecords = filterAgentRecords(agentId, statFrom, statTo);

        AgentPerformanceOverviewResponse response = new AgentPerformanceOverviewResponse();
        response.setAgentId(agentId);
        response.setStatFrom(statFrom.toString());
        response.setStatTo(statTo.toString());
        response.setSampleSize(agentRecords.size());
        response.setHumanCsat(round(avg(agentRecords, item -> scoreFromFive(item.getRatingOverall()))));
        response.setCesAvg(round(avg(agentRecords, item -> scoreFromFive(item.getCesScore()))));
        response.setResolutionRate(round(rate(agentRecords, EvaluationDetailResponse::getResolvedFlag)));
        response.setReopenRate(round(rate(agentRecords, EvaluationDetailResponse::getReopened7d)));
        response.setFirstContactResolutionRate(round(rate(agentRecords, EvaluationDetailResponse::getFirstContactResolvedFlag)));
        response.setQaScoreAvg(round(avg(agentRecords, EvaluationDetailResponse::getQualityLayerScore)));
        response.setEmotionReliefRate(round(reliefRate(agentRecords)));
        response.setFinalScore(round(avg(agentRecords, EvaluationDetailResponse::getFinalServiceScore)));
        response.setScoreCards(buildScoreCards(response));
        return response;
    }

    @Override
    public synchronized List<DailyMetricPoint> getAgentDailyMetrics(Long agentId, LocalDate from, LocalDate to) {
        LocalDate statFrom = from == null ? LocalDate.now().minusDays(6) : from;
        LocalDate statTo = to == null ? LocalDate.now() : to;
        List<DailyMetricPoint> list = new ArrayList<>();
        for (LocalDate date = statFrom; !date.isAfter(statTo); date = date.plusDays(1)) {
            LocalDate currentDate = date;
            List<EvaluationDetailResponse> records = evaluationsById.values().stream()
                    .filter(item -> agentId.equals(item.getHumanAgentId()))
                    .filter(item -> parseDate(item.getCreatedAt()).equals(currentDate))
                    .toList();
            DailyMetricPoint point = new DailyMetricPoint();
            point.setStatDate(currentDate.toString());
            point.setSampleSize(records.size());
            point.setHumanCsat(round(avg(records, item -> scoreFromFive(item.getRatingOverall()))));
            point.setQaScoreAvg(round(avg(records, EvaluationDetailResponse::getQualityLayerScore)));
            point.setEmotionReliefRate(round(reliefRate(records)));
            point.setFinalScore(round(avg(records, EvaluationDetailResponse::getFinalServiceScore)));
            list.add(point);
        }
        return list;
    }

    private List<EvaluationDetailResponse> filterAgentRecords(Long agentId, LocalDate from, LocalDate to) {
        return evaluationsById.values().stream()
                .filter(item -> agentId.equals(item.getHumanAgentId()))
                .filter(item -> {
                    LocalDate createdDate = parseDate(item.getCreatedAt());
                    return !(createdDate.isBefore(from) || createdDate.isAfter(to));
                })
                .sorted(Comparator.comparing(EvaluationDetailResponse::getCreatedAt))
                .map(this::copy)
                .toList();
    }

    private List<ScoreCard> buildScoreCards(AgentPerformanceOverviewResponse response) {
        return List.of(
                scoreCard("human_csat", "Human CSAT", response.getHumanCsat(), response.getHumanCsat(), 20,
                        "Post-service satisfaction score for human service."),
                scoreCard("resolution_rate", "Resolution Rate", response.getResolutionRate(), response.getResolutionRate(), 15,
                        "Share of issues resolved after manual intervention."),
                scoreCard("reopen_rate", "Reopen Control", 100 - safe(response.getReopenRate()), 100 - safe(response.getReopenRate()), 10,
                        "Higher score means fewer reopened cases within 7 days."),
                scoreCard("fcr", "First Contact Resolution", response.getFirstContactResolutionRate(), response.getFirstContactResolutionRate(), 10,
                        "Share of issues closed without another manual round."),
                scoreCard("qa", "QA Score", response.getQaScoreAvg(), response.getQaScoreAvg(), 20,
                        "Quality review score for human service delivery."),
                scoreCard("emotion_relief", "Emotion Relief", response.getEmotionReliefRate(), response.getEmotionReliefRate(), 10,
                        "How often the human agent de-escalates user emotion.")
        );
    }

    private void applyScores(EvaluationDetailResponse detail) {
        double resultLayerScore = weighted(
                scoreFromFive(detail.getRatingOverall()), 20,
                detail.getResolvedFlag() ? 100 : 40, 15,
                detail.getReopened7d() ? 20 : 100, 10
        ) / 45.0 * 100;
        double processLayerScore = weighted(
                responseScore(detail.getFirstHumanResponseSeconds()), 10,
                detail.getFirstContactResolvedFlag() ? 100 : 40, 10,
                detail.getSlaMetFlag() ? 100 : 50, 5
        ) / 25.0 * 100;
        double qualityLayerScore = qualityScore(detail);
        double emotionLayerScore = emotionReliefScore(detail);
        double finalServiceScore =
                resultLayerScore * 0.45 +
                processLayerScore * 0.25 +
                qualityLayerScore * 0.20 +
                emotionLayerScore * 0.10;

        detail.setResultLayerScore(round(resultLayerScore));
        detail.setProcessLayerScore(round(processLayerScore));
        detail.setQualityLayerScore(round(qualityLayerScore));
        detail.setEmotionLayerScore(round(emotionLayerScore));
        detail.setFinalServiceScore(round(finalServiceScore));
    }

    private double qualityScore(EvaluationDetailResponse detail) {
        double attitudeScore = blend(scoreFromFive(detail.getRatingAttitude()), scoreFromFive(detail.getQaAttitudeScore()));
        double professionalScore = blend(scoreFromFive(detail.getRatingProfessional()), scoreFromFive(detail.getQaProfessionalScore()));
        double efficiencyScore = blend(scoreFromFive(detail.getRatingEfficiency()), scoreFromFive(detail.getQaProcessScore()));
        double closureScore = blend(scoreFromFive(detail.getRatingResolution()), scoreFromFive(detail.getQaClosureScore()));
        return weighted(
                attitudeScore, 5,
                professionalScore, 7,
                efficiencyScore, 4,
                closureScore, 4
        ) / 20.0 * 100;
    }

    private double emotionReliefScore(EvaluationDetailResponse detail) {
        String before = detail.getEmotionBeforeHuman();
        String after = detail.getEmotionAfterHuman();
        if (before == null || after == null) {
            return 60;
        }
        int delta = calculateEmotionDelta(before, after);
        if (delta >= 2) {
            return 100;
        }
        if (delta == 1) {
            return 85;
        }
        if (delta == 0) {
            return emotionLevel(before) >= 2 ? 60 : 80;
        }
        return Math.max(0, 60 + delta * 30);
    }

    private double responseScore(Integer seconds) {
        if (seconds == null) {
            return 60;
        }
        if (seconds <= 30) {
            return 100;
        }
        if (seconds <= 60) {
            return 85;
        }
        if (seconds <= 180) {
            return 65;
        }
        return 35;
    }

    private double blend(double userScore, double qaScore) {
        if (qaScore <= 0 && userScore <= 0) {
            return 0;
        }
        if (qaScore <= 0) {
            return userScore;
        }
        if (userScore <= 0) {
            return qaScore;
        }
        return userScore * 0.4 + qaScore * 0.6;
    }

    private double scoreFromFive(Integer value) {
        if (value == null || value <= 0) {
            return 0;
        }
        return value / 5.0 * 100.0;
    }

    private double avg(List<EvaluationDetailResponse> list, ValueExtractor extractor) {
        if (list.isEmpty()) {
            return 0;
        }
        double sum = 0;
        int count = 0;
        for (EvaluationDetailResponse item : list) {
            Double value = extractor.extract(item);
            if (value == null) {
                continue;
            }
            sum += value;
            count++;
        }
        return count == 0 ? 0 : sum / count;
    }

    private double rate(List<EvaluationDetailResponse> list, BooleanExtractor extractor) {
        if (list.isEmpty()) {
            return 0;
        }
        long trueCount = list.stream().filter(item -> extractor.extract(item)).count();
        return trueCount * 100.0 / list.size();
    }

    private double reliefRate(List<EvaluationDetailResponse> list) {
        if (list.isEmpty()) {
            return 0;
        }
        long reliefCount = list.stream()
                .filter(item -> item.getEmotionDelta() != null && item.getEmotionDelta() > 0)
                .count();
        return reliefCount * 100.0 / list.size();
    }

    private double weighted(double firstValue, int firstWeight, double secondValue, int secondWeight, double thirdValue, int thirdWeight) {
        return firstValue * firstWeight / 100.0
                + secondValue * secondWeight / 100.0
                + thirdValue * thirdWeight / 100.0;
    }

    private double weighted(double firstValue, int firstWeight, double secondValue, int secondWeight,
                            double thirdValue, int thirdWeight, double fourthValue, int fourthWeight) {
        return firstValue * firstWeight / 100.0
                + secondValue * secondWeight / 100.0
                + thirdValue * thirdWeight / 100.0
                + fourthValue * fourthWeight / 100.0;
    }

    private ScoreCard scoreCard(String code, String name, Double value, Double score, Integer weight, String description) {
        ScoreCard card = new ScoreCard();
        card.setCode(code);
        card.setName(name);
        card.setValue(round(value));
        card.setScore(round(score));
        card.setWeight(weight);
        card.setDescription(description);
        return card;
    }

    private MetricCategory buildCategory(String code, String name, Integer weight, List<MetricDefinition> metrics) {
        MetricCategory category = new MetricCategory();
        category.setCode(code);
        category.setName(name);
        category.setWeight(weight);
        category.setMetrics(metrics);
        return category;
    }

    private MetricDefinition metric(String code, String name, Integer weight, String description, String formula, String owner) {
        MetricDefinition metric = new MetricDefinition();
        metric.setCode(code);
        metric.setName(name);
        metric.setWeight(weight);
        metric.setDescription(description);
        metric.setFormula(formula);
        metric.setOwner(owner);
        return metric;
    }

    private EvaluationDetailResponse copy(EvaluationDetailResponse source) {
        if (source == null) {
            return null;
        }
        EvaluationDetailResponse target = new EvaluationDetailResponse();
        target.setEvaluationId(source.getEvaluationId());
        target.setSessionId(source.getSessionId());
        target.setHumanAgentId(source.getHumanAgentId());
        target.setUserId(source.getUserId());
        target.setMerchantCode(source.getMerchantCode());
        target.setStatus(source.getStatus());
        target.setRatingOverall(source.getRatingOverall());
        target.setRatingAttitude(source.getRatingAttitude());
        target.setRatingProfessional(source.getRatingProfessional());
        target.setRatingEfficiency(source.getRatingEfficiency());
        target.setRatingResolution(source.getRatingResolution());
        target.setCesScore(source.getCesScore());
        target.setResolvedFlag(source.getResolvedFlag());
        target.setFirstContactResolvedFlag(source.getFirstContactResolvedFlag());
        target.setSlaMetFlag(source.getSlaMetFlag());
        target.setFirstHumanResponseSeconds(source.getFirstHumanResponseSeconds());
        target.setComment(source.getComment());
        target.setEmotionBeforeHuman(source.getEmotionBeforeHuman());
        target.setEmotionAfterHuman(source.getEmotionAfterHuman());
        target.setEmotionDelta(source.getEmotionDelta());
        target.setRecontact72h(source.getRecontact72h());
        target.setReopened7d(source.getReopened7d());
        target.setQaAttitudeScore(source.getQaAttitudeScore());
        target.setQaProfessionalScore(source.getQaProfessionalScore());
        target.setQaProcessScore(source.getQaProcessScore());
        target.setQaClosureScore(source.getQaClosureScore());
        target.setQaComment(source.getQaComment());
        target.setReviewerName(source.getReviewerName());
        target.setResultLayerScore(source.getResultLayerScore());
        target.setProcessLayerScore(source.getProcessLayerScore());
        target.setQualityLayerScore(source.getQualityLayerScore());
        target.setEmotionLayerScore(source.getEmotionLayerScore());
        target.setFinalServiceScore(source.getFinalServiceScore());
        target.setCreatedAt(source.getCreatedAt());
        target.setUpdatedAt(source.getUpdatedAt());
        return target;
    }

    private int calculateEmotionDelta(String before, String after) {
        return emotionLevel(before) - emotionLevel(after);
    }

    private int emotionLevel(String label) {
        if (label == null) {
            return 0;
        }
        return switch (label.toLowerCase()) {
            case "angry" -> 3;
            case "dissatisfied" -> 2;
            case "anxious" -> 1;
            default -> 0;
        };
    }

    private String normalizeEmotion(String label) {
        if (label == null || label.isBlank()) {
            return null;
        }
        String normalized = label.trim().toLowerCase();
        return switch (normalized) {
            case "calm", "anxious", "dissatisfied", "angry" -> normalized;
            default -> normalized;
        };
    }

    private Boolean defaultFalse(Boolean value) {
        return value != null && value;
    }

    private Double round(Double value) {
        if (value == null) {
            return 0.0;
        }
        return Math.round(value * 100.0) / 100.0;
    }

    private double safe(Double value) {
        return value == null ? 0.0 : value;
    }

    private String now() {
        return LocalDateTime.now().format(TIME_FORMATTER);
    }

    private LocalDate parseDate(String text) {
        return LocalDate.parse(text.substring(0, 10));
    }

    @FunctionalInterface
    private interface ValueExtractor {
        Double extract(EvaluationDetailResponse item);
    }

    @FunctionalInterface
    private interface BooleanExtractor {
        boolean extract(EvaluationDetailResponse item);
    }
}
