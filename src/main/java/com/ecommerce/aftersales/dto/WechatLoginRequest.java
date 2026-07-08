package com.ecommerce.aftersales.dto;

import lombok.Data;

@Data
public class WechatLoginRequest {

    /** 微信 wx.login 返回的 code；沙盒模式下可映射为预设 openid */
    private String code;

    /** 沙盒模式可选：直接指定 openid 跳过 code 交换 */
    private String openid;

    private String nickname;

    private String avatarUrl;
}
