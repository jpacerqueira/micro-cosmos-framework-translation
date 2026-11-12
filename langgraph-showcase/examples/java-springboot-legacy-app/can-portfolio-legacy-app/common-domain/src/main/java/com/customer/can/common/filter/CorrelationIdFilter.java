package com.customer.can.common.filter;

import org.apache.logging.log4j.ThreadContext;

import javax.servlet.Filter;
import javax.servlet.FilterChain;
import javax.servlet.FilterConfig;
import javax.servlet.ServletException;
import javax.servlet.ServletRequest;
import javax.servlet.ServletResponse;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.UUID;

public class CorrelationIdFilter implements Filter {
    public static final String CORRELATION_HEADER = "X-Correlation-Id";
    public static final String MDC_CORRELATION = "correlationId";
    public static final String MDC_USER = "userId";
    public static final String MDC_PORTFOLIO = "portfolioId";

    @Override
    public void init(FilterConfig filterConfig) {}

    @Override
    public void doFilter(ServletRequest request, ServletResponse response, FilterChain chain)
            throws IOException, ServletException {
        HttpServletRequest httpRequest = (HttpServletRequest) request;
        String correlationId = httpRequest.getHeader(CORRELATION_HEADER);
        if (correlationId == null || correlationId.isEmpty()) {
            correlationId = UUID.randomUUID().toString();
        }
        ThreadContext.put(MDC_CORRELATION, correlationId);
        ((HttpServletResponse) response).setHeader(CORRELATION_HEADER, correlationId);
        try {
            chain.doFilter(request, response);
        } finally {
            ThreadContext.remove(MDC_CORRELATION);
            ThreadContext.remove(MDC_USER);
            ThreadContext.remove(MDC_PORTFOLIO);
        }
    }

    @Override
    public void destroy() {}
}
