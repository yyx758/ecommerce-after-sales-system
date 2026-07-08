package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.dto.HumanServiceEvaluationDtos.*;

import java.time.LocalDate;
import java.util.List;

public interface HumanServiceEvaluationService {

    MetricDesignResponse getMetricDesign();

    EvaluationDetailResponse submitEvaluation(SubmitEvaluationRequest request);

    EvaluationDetailResponse getEvaluationBySessionId(Long sessionId);

    EvaluationDetailResponse submitQaReview(Long evaluationId, QaReviewRequest request);

    AgentPerformanceOverviewResponse getAgentOverview(Long agentId, LocalDate from, LocalDate to);

    List<DailyMetricPoint> getAgentDailyMetrics(Long agentId, LocalDate from, LocalDate to);
}
