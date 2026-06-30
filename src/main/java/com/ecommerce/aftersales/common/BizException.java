package com.ecommerce.aftersales.common;

import lombok.Getter;

@Getter
public class BizException extends RuntimeException {

    private final Integer code;
    private final Object data;

    public BizException(String message) {
        this(400, message, null);
    }

    public BizException(Integer code, String message) {
        this(code, message, null);
    }

    public BizException(Integer code, String message, Object data) {
        super(message);
        this.code = code;
        this.data = data;
    }
}
