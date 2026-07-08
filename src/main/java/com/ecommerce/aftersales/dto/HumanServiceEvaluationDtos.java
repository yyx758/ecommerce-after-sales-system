package com.ecommerce.aftersales.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

import java.util.List;

public final class HumanServiceEvaluationDtos {

    private HumanServiceEvaluationDtos() {
    }

    @Data
    public static class MetricDesignResponse {
        private String version;
        private String scope;
        private List<MetricCategory> categories;
        private List<String> notes;
    }

    @Data
    public static class MetricCategory {
        private String code;
        private String name;
        private Integer weight;
        private List<MetricDefinition> metrics;
    }

    @Data
    public static class MetricDefinition {
        private String code;
        private String name;
        private Integer weight;
        private String description;
        private String formula;
        private String owner;
    }

    @Data
    public static class SubmitEvaluationRequest {
        @NotNull(message = "sessionId is required")
        private Long sessionId;

        @NotNull(message = "humanAgentId is required")
        private Long humanAgentId;

        private Long userId;
        private String merchantCode;

        @Min(1)
        @Max(5)
        private Integer ratingOverall;

        @Min(1)
        @Max(5)
        private Integer ratingAttitude;

        @Min(1)
        @Max(5)
        private Integer ratingProfessional;

        @Min(1)
        @Max(5)
        private Integer ratingEfficiency;

        @Min(1)
        @Max(5)
        private Integer ratingResolution;

        @Min(1)
        @Max(5)
        private Integer cesScore;

        private Boolean resolvedFlag;
        private Boolean firstContactResolvedFlag;
        private Boolean slaMetFlag;
        private Integer firstHumanResponseSeconds;
        private String comment;
        private String emotionBeforeHuman;
        private String emotionAfterHuman;
        private Boolean recontact72h;
        private Boolean reopened7d;
    }

    @Data
    public static class QaReviewRequest {
        private Integer qaAttitudeScore;
        private Integer qaProfessionalScore;
        private Integer qaProcessScore;
        private Integer qaClosureScore;
        private String qaComment;
        private String reviewerName;
    }

    @Data
    public static class EvaluationDetailResponse {
        private Long evaluationId;
        private Long sessionId;
        private Long humanAgentId;
        private Long userId;
        private String merchantCode;
        private String status;
        private Integer ratingOverall;
        private Integer ratingAttitude;
        private Integer ratingProfessional;
        private Integer ratingEfficiency;
        private Integer ratingResolution;
        private Integer cesScore;
        private Boolean resolvedFlag;
        private Boolean firstContactResolvedFlag;
        private Boolean slaMetFlag;
        private Integer firstHumanResponseSeconds;
        private String comment;
        private String emotionBeforeHuman;
        private String emotionAfterHuman;
        private Integer emotionDelta;
        private Boolean recontact72h;
        private Boolean reopened7d;
        private Integer qaAttitudeScore;
        private Integer qaProfessionalScore;
        private Integer qaProcessScore;
        private Integer qaClosureScore;
        private String qaComment;
        private String reviewerName;
        private Double resultLayerScore;
        private Double processLayerScore;
        private Double qualityLayerScore;
        private Double emotionLayerScore;
        private Double finalServiceScore;
        private String createdAt;
        private String updatedAt;
    }

    @Data
    public static class AgentPerformanceOverviewResponse {
        private Long agentId;
        private String statFrom;
        private String statTo;
        private Integer sampleSize;
        private Double humanCsat;
        private Double cesAvg;
        private Double resolutionRate;
        private Double reopenRate;
        private Double firstContactResolutionRate;
        private Double qaScoreAvg;
        private Double emotionReliefRate;
        private Double finalScore;
        private List<ScoreCard> scoreCards;
    }

    @Data
    public static class ScoreCard {
        private String code;
        private String name;
        private Double value;
        private Double score;
        private Integer weight;
        private String description;
    }

    @Data
    public static class DailyMetricPoint {
        private String statDate;
        private Integer sampleSize;
        private Double humanCsat;
        private Double qaScoreAvg;
        private Double emotionReliefRate;
        private Double finalScore;
    }
}
