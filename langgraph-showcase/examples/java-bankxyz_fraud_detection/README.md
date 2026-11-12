# BankXYZ Fraud Detection

Java 8 / Spring Boot fraud detection service for BankXYZ retail and commercial banking.
Handles both real-time card authorisation screening (sub-180ms) and nightly batch transaction review.

## Quick start

Two ways to run: Docker Compose (recommended, zero local dependencies) or manually.

---

### Docker Compose

**Prerequisites:** Docker Desktop (or Docker Engine + Compose plugin).

```bash
cd examples/java-bankxyz_fraud_detection
docker compose up --build
```

That single command:

1. Builds the Spring Boot fat JAR inside a Maven container (no local JDK or Maven needed).
2. Starts Oracle XE 21c, creates the `FDADMIN` user, and runs the full DDL schema.
3. Starts ActiveMQ 5.18 Classic on the default `FRAUD.ALERT.QUEUE`.
4. Starts the application — only after both Oracle and ActiveMQ pass their health checks.

**On first boot Oracle takes 2–3 minutes** to initialise its data files. The app container waits automatically.

Once all three containers are healthy:

| Service | URL / port |
|---|---|
| Fraud API | `http://localhost:8080` |
| Actuator health | `http://localhost:8080/actuator/health` |
| ActiveMQ web console | `http://localhost:8161` (admin / admin) |
| Oracle listener | `localhost:1521` (service `XEPDB1`) |

#### Stopping

```bash
docker compose down          # stop and remove containers (data volumes kept)
docker compose down -v       # also wipe Oracle and ActiveMQ data volumes
```

#### Credentials

Default credentials are in [.env](.env). Change them before deploying outside a local machine.

To override without editing `.env`:

```bash
ORACLE_FDADMIN_PASSWORD=secret123 docker compose up --build
```

---

### Manual (local JDK / existing Oracle + ActiveMQ)

#### Prerequisites

- Java 8+
- Maven 3.6+
- Oracle Database 10g+
- ActiveMQ 5.x (or IBM MQ — see [Switching to IBM MQ](#switching-to-ibm-mq))

#### Build

```bash
cd examples/java-bankxyz_fraud_detection
mvn clean package
```

#### Database setup

```bash
sqlplus FDADMIN/password@//localhost:1521/ORCL @oracle/install_all.sql
```

See [oracle/](oracle/) for individual table DDL files.

#### Run

```bash
java -jar target/bankxyz-fraud-detection-1.0.0-SNAPSHOT.jar
```

#### Oracle JDBC driver

The Oracle JDBC driver is not in Maven Central for 10g. Two options:

**Option A — install `ojdbc14` manually (Oracle 10g native driver):**
```bash
mvn install:install-file -Dfile=ojdbc14.jar \
  -DgroupId=com.oracle -DartifactId=ojdbc14 \
  -Dversion=10.2.0.5 -Dpackaging=jar
```
Then replace the `ojdbc8` dependency in `pom.xml` with `com.oracle:ojdbc14:10.2.0.5`.

**Option B — use `ojdbc8` (already in `pom.xml`):**
Works for basic connectivity against Oracle 10.x databases.

---

## Testing

Two layers, both self-contained (H2 in place of Oracle, an embedded in-VM
ActiveMQ broker in place of a real one — see
[`src/test/resources/application-test.properties`](src/test/resources/application-test.properties)).
Neither layer touches the Oracle/ActiveMQ containers started by
`docker compose up`; that means `mvn test` and the Docker image build both
run everywhere, with no external services to stand up first.

| Layer | Where | What it's for |
|---|---|---|
| **BDD / Cucumber** | [`src/test/resources/features/`](src/test/resources/features/), [`src/test/java/.../steps/`](src/test/java/com/bankxyz/fraud/steps/) | One `.feature` file per bounded context (fraud scoring, velocity, customer profile, watchlist screening, alert/MQ, real-time authorisation, nightly batch) — readable acceptance criteria traceable to ARCHITECTURE.md, run against the real Spring context, real JPA repositories and a real (embedded) JMS broker |
| **Unit / JUnit 5 + Mockito** | [`src/test/java/.../service/`](src/test/java/com/bankxyz/fraud/service/), `.../web/`, `.../domain/` | Every collaborator mocked, so branches that are impractical to reach through the BDD suite — defensive catch blocks, the composite-score cap, enum edge cases, per-transaction batch error handling — are exercised in isolation |

Run everything:

```bash
cd examples/java-bankxyz_fraud_detection
mvn clean verify
```

or, with zero local JDK/Maven (same container the app image builds with):

```bash
docker compose run --rm tests
```

That produces, on the host (the compose service bind-mounts the repo — see
`tests:` in [`docker-compose.yml`](docker-compose.yml)):

| Report | Path |
|---|---|
| Coverage (line/branch, by class) | `target/site/jacoco/index.html` |
| Cucumber scenario report | `target/cucumber-report/index.html` |
| Raw JUnit XML/TXT | `target/surefire-reports/` |

`mvn verify` also runs a Jacoco coverage gate (`jacoco-check` in `pom.xml`):
**minimum 90% line / 85% branch coverage** on `service`, `web` and `domain` —
the packages with actual branching logic to protect. Entities, DTOs,
repository interfaces and `@Configuration` classes are excluded from the gate
deliberately: they have no logic of their own, and a test whose only purpose
is exercising a getter/setter doesn't pay for its own maintenance cost. The
Docker image build (`docker build .` / `docker compose up --build`) runs this
same `mvn clean verify` in its build stage, so a broken test or a coverage
regression fails the image build, not just CI.

---

## API

### Real-time authorisation check

```
POST /api/v1/authorise
Content-Type: application/json
```

**Request**
```json
{
  "txnId":        "TXN0000000000001",
  "acctNo":       "ACC0000001",
  "txnAmount":    2500.00,
  "merchantCode": "MCH00001",
  "channel":      "ONLINE",
  "txnCountry":   "GBR",
  "cardType":     "DB",
  "cnpFlag":      false
}
```

**Response**
```json
{
  "txnId":      "TXN0000000000001",
  "decision":   "APPROVE",
  "returnCode": "00",
  "fraudScore": 0.3250,
  "message":    "TRANSACTION APPROVED",
  "elapsedMs":  45
}
```

`decision` values:

| Value     | `returnCode` | Condition                                  |
|-----------|--------------|--------------------------------------------|
| `APPROVE` | `00`         | Score < 0.75, or 180ms SLA breached        |
| `REVIEW`  | `20`         | Score ≥ 0.75 — alert created, allowed through |
| `DECLINE` | `10`         | Score ≥ 0.90 — transaction blocked         |

`channel` accepted values: `ATM`, `ONLINE`, `BRANCH`, `CHIPPIN`

### Manual batch trigger

```
POST /api/v1/batch/run
```

Triggers the nightly batch job immediately. Returns `200 OK` with `"Batch job submitted"`.

### Health check

```
GET /actuator/health
```

---

## Fraud scoring

Five independent signals combine into a composite score (0.0–1.0):

| Signal              | Weight | Configurable property              |
|---------------------|--------|------------------------------------|
| Transaction amount  | 0.25   | `fraud.scoring.weight-amount`      |
| Merchant risk band  | 0.25   | `fraud.scoring.weight-merchant`    |
| 24-hour velocity    | 0.20   | `fraud.scoring.weight-velocity`    |
| Profile deviation   | 0.20   | `fraud.scoring.weight-profile`     |
| Watchlist hit       | 0.10   | `fraud.scoring.weight-watchlist`   |

All weights are in `application.properties` — no rebuild needed to change them.

**Channel CHIPPIN:** profile signal weight is zeroed and redistributed to the remaining signals (BAU-2021-09).

---

## Configuration

Key properties in `application.properties`:

```properties
# Oracle 10g
spring.datasource.url=jdbc:oracle:thin:@localhost:1521:ORCL
spring.datasource.username=FDADMIN
spring.datasource.password=changeme
spring.jpa.database-platform=org.hibernate.dialect.Oracle10gDialect

# JMS queue
fraud.mq.alert-queue=FRAUD.ALERT.QUEUE
spring.activemq.broker-url=tcp://localhost:61616

# Scoring thresholds
fraud.scoring.score-threshold=0.7500
fraud.scoring.decline-threshold=0.9000

# SLA limit (milliseconds) — decision defaults to APPROVE if exceeded
fraud.scoring.sla-limit-ms=180

# Nightly batch schedule
fraud.batch.cron=0 0 2 * * ?
fraud.batch.max-transactions=500
```

Full reference in [ARCHITECTURE.md §13](ARCHITECTURE.md#13-configuration-reference-applicationproperties).

---

## Switching to IBM MQ

1. Replace in `pom.xml`:
   ```xml
   <dependency>
     <groupId>com.ibm.mq</groupId>
     <artifactId>mq-jms-spring-boot-starter</artifactId>
     <version>3.3.4</version>
   </dependency>
   ```
2. Update `application.properties`:
   ```properties
   ibm.mq.queueManager=FDQM01
   ibm.mq.channel=FRAUD.CHANNEL
   ibm.mq.connName=mq-host(1414)
   ibm.mq.user=mqadmin
   ibm.mq.password=changeme
   ```
3. Update `JmsConfig.java` to use `MQConnectionFactory`.

The queue name `FRAUD.ALERT.QUEUE` and all JSON field names remain unchanged.

---

## Database schema

Individual Oracle 10g DDL files in [oracle/](oracle/):

| File                      | Object(s)                                      |
|---------------------------|------------------------------------------------|
| `oracle/00_sequences.sql` | All 6 sequences                                |
| `oracle/01_account_master.sql` | `ACCOUNT_MASTER`                          |
| `oracle/02_txn_queue.sql` | `TXN_QUEUE` + 2 indexes                        |
| `oracle/03_merchant_risk.sql` | `MERCHANT_RISK`                           |
| `oracle/04_cust_profile.sql`  | `CUST_PROFILE`                            |
| `oracle/05_watchlist.sql` | `WATCHLIST` + 2 indexes + trigger              |
| `oracle/06_watchlist_hits.sql` | `WATCHLIST_HITS` + 2 indexes + trigger   |
| `oracle/07_fraud_alerts.sql`  | `FRAUD_ALERTS` + 2 indexes                |
| `oracle/08_mq_failure_log.sql` | `MQ_FAILURE_LOG` + index + trigger       |
| `oracle/09_sla_breach_log.sql` | `SLA_BREACH_LOG` + 2 indexes + trigger   |
| `oracle/install_all.sql`  | Master install script (runs all in order)      |

---

## Project structure

```
src/main/java/com/bankxyz/fraud/
├── FraudDetectionApplication.java
├── config/          FraudScoringProperties, JmsConfig
├── domain/          AccountStatus, AlertStatus, AuthDecision, Channel, RiskBand
├── entity/          9 JPA entities
├── repository/      9 Spring Data repositories
├── service/         FraudCommArea + 7 services
├── batch/           FraudBatchJobConfig
└── web/             RealtimeCheckController + DTOs

src/test/
├── java/com/bankxyz/fraud/
│   ├── cucumber/    RunCucumberTest (JUnit Platform Suite entry point), Spring context config
│   ├── steps/       Cucumber step definitions, one class per bounded context
│   ├── support/     Fixtures, TestContext, Hooks, MQ failure-injection test double
│   ├── service/     JUnit 5 + Mockito unit tests — one class per service
│   ├── web/         RealtimeCheckControllerTest
│   └── domain/      Enum edge-case tests (fromCode/fromString branches)
└── resources/
    ├── features/                 *.feature — Gherkin scenarios
    └── application-test.properties   H2 + embedded ActiveMQ profile
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for full design documentation, and the
[Testing](#testing) section above for how to run the suite.
