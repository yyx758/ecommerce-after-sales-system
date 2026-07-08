package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.dto.HumanServiceEvaluationDtos.*;
import com.ecommerce.aftersales.service.HumanServiceEvaluationService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;
import java.util.List;

@RestController
@RequiredArgsConstructor
@RequestMapping("/merchant-cs/human-service-evaluation")
public class HumanServiceEvaluationController {

    private final HumanServiceEvaluationService humanServiceEvaluationService;

    @GetMapping("/design")
    public ApiResponse<MetricDesignResponse> getMetricDesign() {
        return ApiResponse.success("OK", humanServiceEvaluationService.getMetricDesign());
    }

    @PostMapping("/records")
    public ApiResponse<EvaluationDetailResponse> submitEvaluation(@Valid @RequestBody SubmitEvaluationRequest request) {
        return ApiResponse.success("Evaluation submitted", humanServiceEvaluationService.submitEvaluation(request));
    }

    @GetMapping("/records/session/{sessionId}")
    public ApiResponse<EvaluationDetailResponse> getBySessionId(@PathVariable Long sessionId) {
        return ApiResponse.success("OK", humanServiceEvaluationService.getEvaluationBySessionId(sessionId));
    }

    @PostMapping("/records/{evaluationId}/qa-review")
    public ApiResponse<EvaluationDetailResponse> submitQaReview(@PathVariable Long evaluationId,
                                                                @RequestBody QaReviewRequest request) {
        return ApiResponse.success("QA review submitted",
                humanServiceEvaluationService.submitQaReview(evaluationId, request));
    }

    @GetMapping("/agents/{agentId}/overview")
    public ApiResponse<AgentPerformanceOverviewResponse> getAgentOverview(
            @PathVariable Long agentId,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate from,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate to
    ) {
        return ApiResponse.success("OK", humanServiceEvaluationService.getAgentOverview(agentId, from, to));
    }

    @GetMapping("/agents/{agentId}/daily")
    public ApiResponse<List<DailyMetricPoint>> getAgentDailyMetrics(
            @PathVariable Long agentId,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate from,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate to
    ) {
        return ApiResponse.success("OK", humanServiceEvaluationService.getAgentDailyMetrics(agentId, from, to));
    }
}
