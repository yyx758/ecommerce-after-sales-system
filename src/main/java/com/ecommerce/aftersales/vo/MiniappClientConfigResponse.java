package com.ecommerce.aftersales.vo;

import lombok.Builder;
import lombok.Value;

import java.util.List;

@Value
@Builder
public class MiniappClientConfigResponse {
    String environmentCode;
    String environmentLabel;
    String backendOrigin;
    String apiBaseUrl;
    String agentBaseUrl;
    Integer requestTimeout;
    Integer agentRequestTimeout;
    DemoAccount demoAccount;
    WechatSandbox wechatSandbox;
    List<Preset> presets;

    @Value
    @Builder
    public static class DemoAccount {
        Boolean enabled;
        String phone;
        String password;
        String nickname;
    }

    @Value
    @Builder
    public static class WechatSandbox {
        Boolean enabled;
        List<SandboxUser> users;
    }

    @Value
    @Builder
    public static class SandboxUser {
        String openid;
        String code;
        String nickname;
        String avatarUrl;
        String phone;
    }

    @Value
    @Builder
    public static class Preset {
        String code;
        String label;
        String baseOrigin;
        String apiBaseUrl;
        String agentBaseUrl;
        Boolean recommended;
    }
}
