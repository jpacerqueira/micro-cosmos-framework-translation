package com.bankxyz.fraud.cucumber;

import com.bankxyz.fraud.support.TestJmsConfig;
import io.cucumber.spring.CucumberContextConfiguration;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.ActiveProfiles;

/**
 * Boots the full Spring application context once per Cucumber run, backed by
 * the "test" profile (H2 in place of Oracle, embedded ActiveMQ in place of a
 * real broker — see application-test.properties). All step definition classes
 * are wired as Spring beans against this same context.
 */
@CucumberContextConfiguration
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ActiveProfiles("test")
@Import(TestJmsConfig.class)
public class CucumberSpringConfiguration {
}
