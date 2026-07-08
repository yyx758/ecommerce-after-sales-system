package com.ecommerce.aftersales.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.config.MiniappClientProperties;
import com.ecommerce.aftersales.dto.LoginRequest;
import com.ecommerce.aftersales.dto.RegisterRequest;
import com.ecommerce.aftersales.dto.ResetPasswordRequest;
import com.ecommerce.aftersales.dto.WechatLoginRequest;
import com.ecommerce.aftersales.entity.User;
import com.ecommerce.aftersales.mapper.UserMapper;
import com.ecommerce.aftersales.service.UserAuthService;
import com.ecommerce.aftersales.service.VerificationCodeService;
import com.ecommerce.aftersales.util.JwtTokenUtil;
import com.ecommerce.aftersales.vo.LoginResponse;
import com.ecommerce.aftersales.vo.UserProfileResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.util.Optional;
import java.util.UUID;

@Service
@RequiredArgsConstructor
public class UserAuthServiceImpl implements UserAuthService {

    private static final int USER_STATUS_NORMAL = 1;
    private static final int BIND_STATUS_UNBOUND = 0;
    private static final String ROLE_TYPE_USER = "USER";
    private static final String REGISTER_SCENE = "REGISTER";
    private static final String RESET_PASSWORD_SCENE = "RESET_PASSWORD";

    private final UserMapper userMapper;
    private final PasswordEncoder passwordEncoder;
    private final VerificationCodeService verificationCodeService;
    private final JwtTokenUtil jwtTokenUtil;
    private final MiniappClientProperties miniappClientProperties;

    @Override
    @Transactional(rollbackFor = Exception.class)
    public UserProfileResponse register(RegisterRequest request) {
        verificationCodeService.verifyCode(request.getPhone(), REGISTER_SCENE, request.getCode());
        if (findByPhone(request.getPhone()) != null) {
            throw new BizException("手机号已注册");
        }
        if (StringUtils.hasText(request.getOpenid()) && findByOpenid(request.getOpenid()) != null) {
            throw new BizException("微信账号已绑定其他用户");
        }

        User user = new User();
        user.setUserAccount(request.getPhone());
        user.setPhone(request.getPhone());
        user.setPassword(passwordEncoder.encode(request.getPassword()));
        user.setOpenid(request.getOpenid());
        user.setNickname(StringUtils.hasText(request.getNickname()) ? request.getNickname() : "微信用户");
        user.setAvatarUrl(request.getAvatarUrl());
        user.setBindStatus(BIND_STATUS_UNBOUND);
        user.setRoleType(ROLE_TYPE_USER);
        user.setStatus(USER_STATUS_NORMAL);
        user.setDeleted(0);
        userMapper.insert(user);
        return toProfile(user);
    }

    @Override
    public LoginResponse login(LoginRequest request) {
        User user = findByPhone(request.getPhone());
        if (user == null || !passwordEncoder.matches(request.getPassword(), user.getPassword())) {
            throw new BizException("手机号或密码错误");
        }
        if (!Integer.valueOf(USER_STATUS_NORMAL).equals(user.getStatus())) {
            throw new BizException(403, "账号已被禁用，请联系客服");
        }
        user.setLastLoginTime(java.time.LocalDateTime.now());
        userMapper.updateById(user);
        return LoginResponse.builder()
                .token(jwtTokenUtil.generateToken(user.getId(), user.getPhone()))
                .userId(user.getId())
                .userAccount(user.getUserAccount())
                .phone(user.getPhone())
                .nickname(user.getNickname())
                .avatarUrl(user.getAvatarUrl())
                .bindStatus(user.getBindStatus())
                .build();
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public LoginResponse wechatLogin(WechatLoginRequest request) {
        if (!isWechatSandboxEnabled()) {
            throw new BizException("微信登录沙盒未启用，请配置 app.miniapp.client.wechat-sandbox.enabled");
        }
        ResolvedWechatIdentity identity = resolveWechatIdentity(request);
        User user = findByOpenid(identity.openid());
        boolean newUser = false;
        if (user == null) {
            user = createWechatUser(identity);
            newUser = true;
        } else {
            user = refreshWechatProfile(user, identity);
        }
        if (!Integer.valueOf(USER_STATUS_NORMAL).equals(user.getStatus())) {
            throw new BizException(403, "账号已被禁用，请联系客服");
        }
        user.setLastLoginTime(java.time.LocalDateTime.now());
        userMapper.updateById(user);
        return buildLoginResponse(user, newUser);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void resetPassword(ResetPasswordRequest request) {
        if (!request.getNewPassword().equals(request.getConfirmPassword())) {
            throw new BizException("两次输入密码不同");
        }
        verificationCodeService.verifyCode(request.getPhone(), RESET_PASSWORD_SCENE, request.getCode());
        User user = findByPhone(request.getPhone());
        if (user == null) {
            throw new BizException("用户不存在");
        }
        user.setPassword(passwordEncoder.encode(request.getNewPassword()));
        userMapper.updateById(user);
    }

    private User findByPhone(String phone) {
        return userMapper.selectOne(new LambdaQueryWrapper<User>()
                .eq(User::getPhone, phone)
                .last("limit 1"));
    }

    private User findByOpenid(String openid) {
        return userMapper.selectOne(new LambdaQueryWrapper<User>()
                .eq(User::getOpenid, openid)
                .last("limit 1"));
    }

    private boolean isWechatSandboxEnabled() {
        MiniappClientProperties.WechatSandbox sandbox = miniappClientProperties.getWechatSandbox();
        return sandbox != null && Boolean.TRUE.equals(sandbox.getEnabled());
    }

    private ResolvedWechatIdentity resolveWechatIdentity(WechatLoginRequest request) {
        if (request == null) {
            throw new BizException("微信登录参数不能为空");
        }
        if (StringUtils.hasText(request.getOpenid())) {
            MiniappClientProperties.SandboxUser preset = findSandboxUserByOpenid(request.getOpenid());
            return new ResolvedWechatIdentity(
                    request.getOpenid(),
                    firstNonBlank(request.getNickname(), preset == null ? null : preset.getNickname(), "微信用户"),
                    firstNonBlank(request.getAvatarUrl(), preset == null ? null : preset.getAvatarUrl()),
                    preset == null ? null : preset.getPhone()
            );
        }
        if (!StringUtils.hasText(request.getCode())) {
            throw new BizException("请提供微信登录 code 或沙盒 openid");
        }
        MiniappClientProperties.SandboxUser preset = findSandboxUserByCode(request.getCode());
        if (preset != null) {
            return new ResolvedWechatIdentity(
                    preset.getOpenid(),
                    firstNonBlank(request.getNickname(), preset.getNickname(), "微信用户"),
                    firstNonBlank(request.getAvatarUrl(), preset.getAvatarUrl()),
                    preset.getPhone()
            );
        }
        String openid = "sandbox:" + request.getCode();
        return new ResolvedWechatIdentity(
                openid,
                firstNonBlank(request.getNickname(), "微信用户"),
                request.getAvatarUrl(),
                null
        );
    }

    private MiniappClientProperties.SandboxUser findSandboxUserByCode(String code) {
        return Optional.ofNullable(miniappClientProperties.getWechatSandbox())
                .map(MiniappClientProperties.WechatSandbox::getUsers)
                .orElse(java.util.List.of())
                .stream()
                .filter(user -> code.equals(user.getCode()))
                .findFirst()
                .orElse(null);
    }

    private MiniappClientProperties.SandboxUser findSandboxUserByOpenid(String openid) {
        return Optional.ofNullable(miniappClientProperties.getWechatSandbox())
                .map(MiniappClientProperties.WechatSandbox::getUsers)
                .orElse(java.util.List.of())
                .stream()
                .filter(user -> openid.equals(user.getOpenid()))
                .findFirst()
                .orElse(null);
    }

    private User createWechatUser(ResolvedWechatIdentity identity) {
        User user = new User();
        user.setOpenid(identity.openid());
        user.setUserAccount("wx_" + identity.openid());
        user.setPhone(resolveWechatPhone(identity));
        user.setPassword(passwordEncoder.encode(UUID.randomUUID().toString()));
        user.setNickname(identity.nickname());
        user.setAvatarUrl(identity.avatarUrl());
        user.setBindStatus(BIND_STATUS_UNBOUND);
        user.setRoleType(ROLE_TYPE_USER);
        user.setStatus(USER_STATUS_NORMAL);
        user.setDeleted(0);
        userMapper.insert(user);
        return user;
    }

    private User refreshWechatProfile(User user, ResolvedWechatIdentity identity) {
        boolean changed = false;
        if (StringUtils.hasText(identity.nickname()) && !identity.nickname().equals(user.getNickname())) {
            user.setNickname(identity.nickname());
            changed = true;
        }
        if (StringUtils.hasText(identity.avatarUrl()) && !identity.avatarUrl().equals(user.getAvatarUrl())) {
            user.setAvatarUrl(identity.avatarUrl());
            changed = true;
        }
        return changed ? user : user;
    }

    private String resolveWechatPhone(ResolvedWechatIdentity identity) {
        if (StringUtils.hasText(identity.phone())) {
            if (findByPhone(identity.phone()) != null) {
                throw new BizException("沙盒手机号已被占用: " + identity.phone());
            }
            return identity.phone();
        }
        for (int index = 1; index <= 99; index++) {
            String candidate = String.format("199%08d", index);
            if (findByPhone(candidate) == null) {
                return candidate;
            }
        }
        throw new BizException("无法分配沙盒手机号，请检查配置");
    }

    private LoginResponse buildLoginResponse(User user, boolean newUser) {
        String tokenSubject = StringUtils.hasText(user.getPhone()) ? user.getPhone() : user.getOpenid();
        return LoginResponse.builder()
                .token(jwtTokenUtil.generateToken(user.getId(), tokenSubject))
                .userId(user.getId())
                .userAccount(user.getUserAccount())
                .phone(user.getPhone())
                .nickname(user.getNickname())
                .avatarUrl(user.getAvatarUrl())
                .bindStatus(user.getBindStatus())
                .openid(user.getOpenid())
                .newUser(newUser)
                .build();
    }

    private String firstNonBlank(String... values) {
        if (values == null) {
            return null;
        }
        for (String value : values) {
            if (StringUtils.hasText(value)) {
                return value;
            }
        }
        return null;
    }

    private record ResolvedWechatIdentity(String openid, String nickname, String avatarUrl, String phone) {
    }

    private UserProfileResponse toProfile(User user) {
        return UserProfileResponse.builder()
                .userId(user.getId())
                .userAccount(user.getUserAccount())
                .phone(user.getPhone())
                .nickname(user.getNickname())
                .avatarUrl(user.getAvatarUrl())
                .bindStatus(user.getBindStatus())
                .build();
    }
}
