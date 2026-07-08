package com.ecommerce.aftersales.config;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.entity.SysUser;
import com.ecommerce.aftersales.mapper.SysUserMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.CommandLineRunner;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.crypto.password.PasswordEncoder;

@Configuration
@Slf4j
public class DataInitializer implements CommandLineRunner {

    private final SysUserMapper sysUserMapper;
    private final PasswordEncoder passwordEncoder;

    public DataInitializer(SysUserMapper sysUserMapper, PasswordEncoder passwordEncoder) {
        this.sysUserMapper = sysUserMapper;
        this.passwordEncoder = passwordEncoder;
    }

    @Override
    public void run(String... args) {
        try {
            initAdminAccount();
            initStaffAccount();
        } catch (Exception exception) {
            log.warn("Skip default account initialization because DB is unavailable: {}", exception.getMessage());
        }
    }

    private void initAdminAccount() {
        String account = "admin_demo";
        SysUser existing = sysUserMapper.selectOne(new LambdaQueryWrapper<SysUser>()
                .eq(SysUser::getUsername, account)
                .eq(SysUser::getRoleType, "ADMIN")
                .last("limit 1"));

        if (existing != null) {
            if (!passwordEncoder.matches("123456", existing.getPassword())) {
                existing.setPassword(passwordEncoder.encode("123456"));
                sysUserMapper.updateById(existing);
                log.info("Reset default admin password: admin_demo / 123456");
            }
            return;
        }

        SysUser admin = new SysUser();
        admin.setUsername(account);
        admin.setPassword(passwordEncoder.encode("123456"));
        admin.setMerchantCode("ADMIN_PLATFORM");
        admin.setRealName("Platform Admin");
        admin.setPhone("13800138000");
        admin.setEmail("admin_demo@example.com");
        admin.setRoleType("ADMIN");
        admin.setStatus(1);
        admin.setOnlineStatus(1);
        admin.setMaxSessions(0);
        admin.setDeleted(0);
        sysUserMapper.insert(admin);
        log.info("Created default admin account: admin_demo / 123456");
    }

    private void initStaffAccount() {
        String account = "cs_demo";
        String merchantCode = "MERCHANT_DEMO";

        SysUser existing = sysUserMapper.selectOne(new LambdaQueryWrapper<SysUser>()
                .eq(SysUser::getUsername, account)
                .eq(SysUser::getMerchantCode, merchantCode)
                .last("limit 1"));

        if (existing != null) {
            if (!passwordEncoder.matches("123456", existing.getPassword())) {
                existing.setPassword(passwordEncoder.encode("123456"));
                sysUserMapper.updateById(existing);
                log.info("Reset default staff password: cs_demo / 123456");
            }
            return;
        }

        SysUser staff = new SysUser();
        staff.setUsername(account);
        staff.setPassword(passwordEncoder.encode("123456"));
        staff.setMerchantCode(merchantCode);
        staff.setRealName("Demo Agent");
        staff.setPhone("13800000001");
        staff.setEmail("cs_demo@example.com");
        staff.setRoleType("AGENT");
        staff.setStatus(1);
        staff.setOnlineStatus(1);
        staff.setMaxSessions(8);
        staff.setDeleted(0);
        sysUserMapper.insert(staff);
        log.info("Created default staff account: cs_demo / 123456 / MERCHANT_DEMO");
    }
}
