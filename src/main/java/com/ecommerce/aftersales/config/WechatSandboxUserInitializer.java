package com.ecommerce.aftersales.config;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.entity.User;
import com.ecommerce.aftersales.mapper.UserMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.util.StringUtils;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Slf4j
@Configuration
@RequiredArgsConstructor
public class WechatSandboxUserInitializer {

    private static final int USER_STATUS_NORMAL = 1;
    private static final int BIND_STATUS_UNBOUND = 0;
    private static final String ROLE_TYPE_USER = "USER";

    private final UserMapper userMapper;
    private final PasswordEncoder passwordEncoder;
    private final MiniappClientProperties properties;

    @Bean
    public ApplicationRunner ensureWechatSandboxUsers() {
        return args -> {
            try {
                MiniappClientProperties.WechatSandbox sandbox = properties.getWechatSandbox();
                if (sandbox == null || !Boolean.TRUE.equals(sandbox.getEnabled())) {
                    return;
                }
                List<MiniappClientProperties.SandboxUser> users = Optional.ofNullable(sandbox.getUsers()).orElse(List.of());
                for (MiniappClientProperties.SandboxUser sandboxUser : users) {
                    if (!StringUtils.hasText(sandboxUser.getOpenid())) {
                        continue;
                    }
                    User existing = userMapper.selectOne(new LambdaQueryWrapper<User>()
                            .eq(User::getOpenid, sandboxUser.getOpenid())
                            .last("limit 1"));
                    if (existing != null) {
                        continue;
                    }
                    User user = new User();
                    user.setOpenid(sandboxUser.getOpenid());
                    user.setUserAccount("wx_" + sandboxUser.getOpenid());
                    user.setPhone(resolvePhone(sandboxUser));
                    user.setPassword(passwordEncoder.encode(UUID.randomUUID().toString()));
                    user.setNickname(StringUtils.hasText(sandboxUser.getNickname()) ? sandboxUser.getNickname() : "微信用户");
                    user.setAvatarUrl(sandboxUser.getAvatarUrl());
                    user.setBindStatus(BIND_STATUS_UNBOUND);
                    user.setRoleType(ROLE_TYPE_USER);
                    user.setStatus(USER_STATUS_NORMAL);
                    user.setDeleted(0);
                    userMapper.insert(user);
                    log.info("已初始化微信沙盒用户: {} ({})", sandboxUser.getNickname(), sandboxUser.getOpenid());
                }
            } catch (Exception exception) {
                log.warn("跳过微信沙盒用户初始化，数据库当前不可用: {}", exception.getMessage());
            }
        };
    }

    private String resolvePhone(MiniappClientProperties.SandboxUser sandboxUser) {
        if (StringUtils.hasText(sandboxUser.getPhone())) {
            User existing = userMapper.selectOne(new LambdaQueryWrapper<User>()
                    .eq(User::getPhone, sandboxUser.getPhone())
                    .last("limit 1"));
            if (existing == null) {
                return sandboxUser.getPhone();
            }
        }
        for (int index = 1; index <= 99; index++) {
            String candidate = String.format("199%08d", index);
            User existing = userMapper.selectOne(new LambdaQueryWrapper<User>()
                    .eq(User::getPhone, candidate)
                    .last("limit 1"));
            if (existing == null) {
                return candidate;
            }
        }
        throw new IllegalStateException("无法分配沙盒手机号");
    }
}
