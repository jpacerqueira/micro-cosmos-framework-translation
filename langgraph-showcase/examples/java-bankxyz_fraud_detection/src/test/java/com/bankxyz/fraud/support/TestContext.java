package com.bankxyz.fraud.support;

import com.bankxyz.fraud.service.FraudCommArea;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * Scenario-scoped scratch space shared between step definition classes.
 * cucumber-spring gives every scenario a fresh glue context, so a plain
 * singleton bean here behaves as "one instance per scenario" — reset
 * explicitly in {@link Hooks} as a safety net against context caching.
 */
@Component
public class TestContext {

    private FraudCommArea commArea;
    private String batchSummary;
    private ResponseEntity<Map> authoriseResponse;
    private ResponseEntity<String> batchTriggerResponse;

    public void reset() {
        commArea = null;
        batchSummary = null;
        authoriseResponse = null;
        batchTriggerResponse = null;
    }

    public FraudCommArea getCommArea() { return commArea; }
    public void setCommArea(FraudCommArea v) { this.commArea = v; }

    public String getBatchSummary() { return batchSummary; }
    public void setBatchSummary(String v) { this.batchSummary = v; }

    public ResponseEntity<Map> getAuthoriseResponse() { return authoriseResponse; }
    public void setAuthoriseResponse(ResponseEntity<Map> v) { this.authoriseResponse = v; }

    public ResponseEntity<String> getBatchTriggerResponse() { return batchTriggerResponse; }
    public void setBatchTriggerResponse(ResponseEntity<String> v) { this.batchTriggerResponse = v; }
}
