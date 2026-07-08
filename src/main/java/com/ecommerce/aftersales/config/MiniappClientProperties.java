package com.ecommerce.aftersales.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.ArrayList;
import java.util.List;

@Data
@ConfigurationProperties(prefix = "app.miniapp.client")
public class MiniappClientProperties {

    private String environmentCode = "local";

    private String environmentLabel = "本机开发环境";

    private String apiPath = "/api";

    private Integer requestTimeoutMillis = 15000;

    private Integer agentRequestTimeoutMillis = 90000;

    private List<Preset> presets = new ArrayList<>();

    private DemoUser demoUser = new DemoUser();

    private WechatSandbox wechatSandbox = new WechatSandbox();

    @Data
    public static class Preset {
        private String code;
        private String label;
        private String baseOrigin;
        private Boolean recommended = false;
    }

    @Data
    public static class DemoUser {
        private Boolean enabled = true;
        private String phone = "13800138000";
        private String password = "123456";
        private String nickname = "演示用户";
    }

    @Data
    public static class WechatSandbox {
        private Boolean enabled = true;
        private List<SandboxUser> users = new ArrayList<>();
    }

    @Data
    public static class SandboxUser {
        private String openid;
        private String code;
        private String nickname;
        private String avatarUrl;
        private String phone;
    }
}
