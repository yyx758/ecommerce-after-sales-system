package com.ecommerce.aftersales.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.common.PageResult;
import com.ecommerce.aftersales.dto.AdminConsoleDtos.*;
import com.ecommerce.aftersales.entity.ChatSession;
import com.ecommerce.aftersales.entity.SysUser;
import com.ecommerce.aftersales.mapper.ChatSessionMapper;
import com.ecommerce.aftersales.mapper.SysUserMapper;
import com.ecommerce.aftersales.service.AdminConsoleService;
import com.ecommerce.aftersales.util.JwtTokenUtil;
import lombok.RequiredArgsConstructor;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Optional;

@Service
@RequiredArgsConstructor
public class AdminConsoleServiceImpl implements AdminConsoleService {

    private static final String ADMIN_MERCHANT_CODE = "ADMIN_PLATFORM";
    private static final String DEFAULT_AGENT_PASSWORD = "123456";
    private static final DateTimeFormatter DATE_TIME_FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final SysUserMapper sysUserMapper;
    private final ChatSessionMapper chatSessionMapper;
    private final PasswordEncoder passwordEncoder;
    private final JwtTokenUtil jwtTokenUtil;

    @Override
    @Transactional(rollbackFor = Exception.class)
    public AdminLoginResponse login(AdminLoginRequest request) {
        if (!StringUtils.hasText(request.getAccount()) || !StringUtils.hasText(request.getPassword())) {
            throw new BizException("请输入管理员账号和密码");
        }
        SysUser admin = findAdminByAccount(request.getAccount().trim());
        if (admin == null && "admin_demo".equals(request.getAccount().trim())) {
            admin = createDemoAdmin();
        }
        if (admin == null || !passwordEncoder.matches(request.getPassword(), admin.getPassword())) {
            throw new BizException("管理员账号或密码错误");
        }
        if (!Integer.valueOf(1).equals(admin.getStatus())) {
            throw new BizException(403, "管理员账号已被禁用");
        }
        admin.setLastLoginTime(LocalDateTime.now());
        admin.setOnlineStatus(1);
        sysUserMapper.updateById(admin);

        AdminLoginResponse response = new AdminLoginResponse();
        response.setToken(jwtTokenUtil.generateToken(admin.getId(), Optional.ofNullable(admin.getPhone()).orElse(admin.getUsername())));
        response.setAdmin(toAdminProfile(admin));
        return response;
    }

    @Override
    public void logout() {
    }

    @Override
    public AdminProfile getCurrentAdmin() {
        return toAdminProfile(ensureAdmin());
    }

    @Override
    public AdminOverview getOverview() {
        ensureAdmin();
        List<SysUser> staffAccounts = listAgentUsers();
        long activeCount = staffAccounts.stream().filter(item -> Integer.valueOf(1).equals(item.getStatus())).count();
        long disabledCount = staffAccounts.size() - activeCount;
        long onlineCount = staffAccounts.stream().filter(item -> Integer.valueOf(1).equals(item.getOnlineStatus())).count();
        long merchantCount = staffAccounts.stream()
                .map(item -> Optional.ofNullable(item.getMerchantCode()).orElse(""))
                .filter(StringUtils::hasText)
                .distinct()
                .count();

        AdminOverview overview = new AdminOverview();
        overview.setGreeting("您好，" + Optional.ofNullable(ensureAdmin().getRealName()).orElse("管理员"));
        overview.setSubtitle("统一管理客服账号、商家归属与基础接待配置");
        overview.setStats(List.of(
                stat("客服账号", staffAccounts.size(), "blue"),
                stat("启用账号", activeCount, "green"),
                stat("在线客服", onlineCount, "orange"),
                stat("商家数量", merchantCount, "slate"),
                stat("停用账号", disabledCount, "red")
        ));
        overview.setFocus(List.of(
                "账号创建与编辑已接入真实后端，客服编号由后台按账号 ID 自动生成。",
                "客服登录只使用账号、密码和商家编码，不再依赖前端录入客服编号。",
                "重置密码会恢复为默认初始密码 123456，建议首次登录后尽快修改。"
        ));
        return overview;
    }

    @Override
    public PageResult<ServiceAccountView> listServiceAccounts(long page, long size) {
        ensureAdmin();
        List<ServiceAccountView> records = listAgentUsers().stream()
                .map(this::toServiceAccountView)
                .toList();
        return PageResult.of(records, page, size);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public ServiceAccountView createServiceAccount(ServiceAccountUpsertRequest request) {
        ensureAdmin();
        validateServiceAccountRequest(request);
        String merchantCode = normalizeMerchantCode(request.getMerchantCode());
        if (findStaffByAccount(request.getAccount().trim()) != null) {
            throw new BizException("该商家下账号已存在");
        }

        SysUser staff = new SysUser();
        staff.setUsername(request.getAccount().trim());
        staff.setPassword(passwordEncoder.encode(DEFAULT_AGENT_PASSWORD));
        staff.setMerchantCode(merchantCode);
        staff.setRealName(request.getRealName().trim());
        staff.setPhone(blankToNull(request.getPhone()));
        staff.setRoleType(toRoleType(request.getRole()));
        staff.setStatus(toStatusValue(request.getStatus()));
        staff.setOnlineStatus(Integer.valueOf(1).equals(staff.getStatus()) ? 0 : 0);
        staff.setMaxSessions(normalizeMaxSessions(request.getMaxSessionCount()));
        staff.setDeleted(0);
        sysUserMapper.insert(staff);
        return toServiceAccountView(staff);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public ServiceAccountView updateServiceAccount(Long accountId, ServiceAccountUpsertRequest request) {
        ensureAdmin();
        validateServiceAccountRequest(request);
        SysUser staff = findAgentById(accountId);
        String merchantCode = normalizeMerchantCode(request.getMerchantCode());

        SysUser duplicate = findStaffByAccount(request.getAccount().trim());
        if (duplicate != null && !duplicate.getId().equals(staff.getId())) {
            throw new BizException("该商家下账号已存在");
        }

        staff.setUsername(request.getAccount().trim());
        staff.setMerchantCode(merchantCode);
        staff.setRealName(request.getRealName().trim());
        staff.setPhone(blankToNull(request.getPhone()));
        staff.setRoleType(toRoleType(request.getRole()));
        staff.setStatus(toStatusValue(request.getStatus()));
        staff.setMaxSessions(normalizeMaxSessions(request.getMaxSessionCount()));
        if (!Integer.valueOf(1).equals(staff.getStatus())) {
            staff.setOnlineStatus(0);
        }
        sysUserMapper.updateById(staff);
        return toServiceAccountView(staff);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public PasswordResetView resetServiceAccountPassword(Long accountId) {
        ensureAdmin();
        SysUser staff = findAgentById(accountId);
        staff.setPassword(passwordEncoder.encode(DEFAULT_AGENT_PASSWORD));
        sysUserMapper.updateById(staff);

        PasswordResetView view = new PasswordResetView();
        view.setAccountId(staff.getId());
        view.setAccount(staff.getUsername());
        view.setTemporaryPassword(DEFAULT_AGENT_PASSWORD);
        return view;
    }

    private void validateServiceAccountRequest(ServiceAccountUpsertRequest request) {
        if (!StringUtils.hasText(request.getAccount())
                || !StringUtils.hasText(request.getRealName())
                || !StringUtils.hasText(request.getMerchantCode())) {
            throw new BizException("请填写账号、姓名和商家编码");
        }
    }

    private List<SysUser> listAgentUsers() {
        return sysUserMapper.selectList(new LambdaQueryWrapper<SysUser>()
                .eq(SysUser::getRoleType, "AGENT")
                .orderByDesc(SysUser::getCreateTime));
    }

    private SysUser findAdminByAccount(String account) {
        return sysUserMapper.selectOne(new LambdaQueryWrapper<SysUser>()
                .eq(SysUser::getUsername, account)
                .eq(SysUser::getRoleType, "ADMIN")
                .last("limit 1"));
    }

    private SysUser findStaffByAccount(String account) {
        return sysUserMapper.selectOne(new LambdaQueryWrapper<SysUser>()
                .eq(SysUser::getUsername, account)
                .eq(SysUser::getRoleType, "AGENT")
                .last("limit 1"));
    }

    private SysUser findAgentById(Long accountId) {
        SysUser staff = sysUserMapper.selectById(accountId);
        if (staff == null || !"AGENT".equalsIgnoreCase(staff.getRoleType())) {
            throw new BizException(404, "客服账号不存在");
        }
        return staff;
    }

    private SysUser ensureAdmin() {
        Long adminId = currentUserId();
        if (adminId == null) {
            throw new BizException(401, "未登录，请先登录管理员账号");
        }
        SysUser admin = sysUserMapper.selectById(adminId);
        if (admin == null || !"ADMIN".equalsIgnoreCase(admin.getRoleType())) {
            throw new BizException(403, "当前账号没有管理员权限");
        }
        if (!Integer.valueOf(1).equals(admin.getStatus())) {
            throw new BizException(403, "管理员账号已被禁用");
        }
        return admin;
    }

    private SysUser createDemoAdmin() {
        SysUser admin = new SysUser();
        admin.setUsername("admin_demo");
        admin.setPassword(passwordEncoder.encode(DEFAULT_AGENT_PASSWORD));
        admin.setMerchantCode(ADMIN_MERCHANT_CODE);
        admin.setRealName("Platform Admin");
        admin.setPhone("13800138000");
        admin.setRoleType("ADMIN");
        admin.setStatus(1);
        admin.setOnlineStatus(1);
        admin.setMaxSessions(0);
        admin.setDeleted(0);
        sysUserMapper.insert(admin);
        return admin;
    }

    private AdminProfile toAdminProfile(SysUser admin) {
        AdminProfile profile = new AdminProfile();
        profile.setAdminId(admin.getId());
        profile.setAccount(admin.getUsername());
        profile.setRealName(admin.getRealName());
        profile.setRole("ADMIN");
        profile.setScope("账号治理与运营配置");
        profile.setPhone(admin.getPhone());
        return profile;
    }

    private ServiceAccountView toServiceAccountView(SysUser staff) {
        ServiceAccountView view = new ServiceAccountView();
        view.setId(staff.getId());
        view.setStaffNo("CS" + String.format("%04d", staff.getId()));
        view.setAccount(staff.getUsername());
        view.setRealName(staff.getRealName());
        view.setMerchantCode(staff.getMerchantCode());
        view.setPhone(staff.getPhone());
        view.setRole("CUSTOMER_SERVICE");
        view.setStatus(Integer.valueOf(1).equals(staff.getStatus()) ? "ACTIVE" : "DISABLED");
        view.setOnlineStatus(toOnlineStatusText(staff.getOnlineStatus()));
        view.setMaxSessionCount(staff.getMaxSessions());
        view.setCurrentSessionCount(currentSessionCount(staff.getId()));
        view.setKnowledgeScope(defaultKnowledgeScope(staff.getMerchantCode()));
        view.setLastLoginTime(format(staff.getLastLoginTime()));
        view.setNote("后台绑定客服编号，管理员维护账号与商家归属。");
        return view;
    }

    private int currentSessionCount(Long staffId) {
        Long count = chatSessionMapper.selectCount(new LambdaQueryWrapper<ChatSession>()
                .eq(ChatSession::getHumanAgentId, staffId)
                .ne(ChatSession::getStatus, "CLOSED"));
        return count == null ? 0 : count.intValue();
    }

    private String defaultKnowledgeScope(String merchantCode) {
        if (!StringUtils.hasText(merchantCode)) {
            return "通用售后";
        }
        return merchantCode + " / 通用售后";
    }

    private StatItem stat(String label, Object value, String accent) {
        StatItem item = new StatItem();
        item.setLabel(label);
        item.setValue(value);
        item.setAccent(accent);
        return item;
    }

    private String toOnlineStatusText(Integer onlineStatus) {
        return switch (Optional.ofNullable(onlineStatus).orElse(0)) {
            case 1 -> "ONLINE";
            case 2 -> "BUSY";
            default -> "OFFLINE";
        };
    }

    private Integer toStatusValue(String status) {
        return "DISABLED".equalsIgnoreCase(status) ? 0 : 1;
    }

    private String toRoleType(String role) {
        return StringUtils.hasText(role) && !"CUSTOMER_SERVICE".equalsIgnoreCase(role) ? role.trim() : "AGENT";
    }

    private int normalizeMaxSessions(Integer maxSessionCount) {
        return maxSessionCount == null || maxSessionCount < 1 ? 8 : maxSessionCount;
    }

    private String normalizeMerchantCode(String merchantCode) {
        return StringUtils.hasText(merchantCode) ? merchantCode.trim() : "MERCHANT_DEMO";
    }

    private String blankToNull(String value) {
        return StringUtils.hasText(value) ? value.trim() : null;
    }

    private String format(LocalDateTime value) {
        return value == null ? "未登录" : DATE_TIME_FORMATTER.format(value);
    }

    private Long currentUserId() {
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
}
