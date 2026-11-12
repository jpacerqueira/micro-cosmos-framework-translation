Create a complete legacy Java 8 reference application at `examples/java-springboot-legacy-app/` in the repo at `/Users/joao.cerqueira/Documents/GitHub/micro-cosmos`. This is the legacy equivalent of the modern Axon Framework app in `examples/java-axonframework-modern-app/`.

## PURPOSE
Show the same CAN (Customer-Application-Name) property portfolio business functionality but using legacy tech: Java 8 + Spring Boot 2.7.x + Oracle XE + ActiveMQ + Log4j2. The output serves as a teaching contrast: modern vs legacy. Must work under both docker-compose (local dev) and Kubernetes (production).

## TECH STACK MAPPING
| Modern | Legacy |
|--------|--------|
| Java 21 | Java 8 |
| Spring Boot 3.2 | Spring Boot 2.7.18 |
| Axon Framework (CQRS/ES) | Spring MVC + JPA + append-only audit log |
| NATS JetStream | Apache ActiveMQ 5.x (JMS) |
| PostgreSQL + Citus | Oracle XE 21 (gvenzl/oracle-xe:21-slim — Oracle 10g dialect) |
| GraphQL BFF | REST + Springfox Swagger 2 |
| Azure AD OAuth2 | Spring Security + JJWT 0.9.x |
| React 18 + Vite | Simple HTML + vanilla JS |
| Logback JSON | Log4j2 with JsonLayout + MDC |
| Istio service mesh | plain nginx-ingress |
| NATS DLQ | ActiveMQ dead-letter queue |

## BUSINESS DOMAIN (from architecture spec)
Five bounded contexts:
1. `property-allocation` — portfolio CRUD, property allocation, valuation submission, broker assignment, portfolio closure. Has Oracle JPA entities: PORTFOLIO, PROPERTY, PROPERTY_VALUATION, BROKER_ALLOCATION, PROPERTY_JOURNAL (append-only audit). Seed data: 2 portfolios, 5 properties, seed users.
2. `user-auth` — users, companies, JWT login/refresh. Roles: PORTFOLIO_ADMIN, BROKER, VALUER, VIEWER, SYS_ADMIN.
3. `vdr-ingestion` — document upload REST, Apache Tika extraction, store metadata in Oracle.
4. `workflow` — allocation state machine (Spring State Machine): PENDING → BROKER_ASSIGNED → VALUER_ASSIGNED → VALUED → CLOSED. Driven by JMS events from property-allocation.
5. `search` — JDBC-based search across portfolios, properties, documents stored in Oracle.
6. `webapp-bff` — REST aggregation layer that calls the other services via RestTemplate. Swagger UI on port 8080.

## DIRECTORY STRUCTURE TO CREATE

```
examples/java-springboot-legacy-app/
├── README.md
├── docker-compose.local.yml
├── can-portfolio-legacy-app/
│   ├── pom.xml          (parent POM, Java 8, Spring Boot 2.7.18)
│   ├── Dockerfile
│   ├── .dockerignore
│   ├── common-domain/
│   │   ├── pom.xml
│   │   └── src/main/java/com/customer/can/common/
│   │       ├── dto/PortfolioDto.java
│   │       ├── dto/PropertyDto.java
│   │       ├── dto/UserDto.java
│   │       ├── event/DomainEvent.java
│   │       ├── messaging/JmsEnvelope.java
│   │       └── filter/CorrelationIdFilter.java
│   ├── property-allocation/
│   │   ├── pom.xml
│   │   └── src/main/
│   │       ├── java/com/customer/can/property/
│   │       │   ├── PropertyAllocationApplication.java
│   │       │   ├── domain/Portfolio.java (JPA entity)
│   │       │   ├── domain/Property.java
│   │       │   ├── domain/PropertyValuation.java
│   │       │   ├── domain/BrokerAllocation.java
│   │       │   ├── domain/AuditEventLog.java
│   │       │   ├── repository/PortfolioRepository.java
│   │       │   ├── repository/PropertyRepository.java
│   │       │   ├── service/PortfolioService.java
│   │       │   ├── api/PortfolioController.java
│   │       │   ├── api/PropertyController.java
│   │       │   ├── messaging/JmsEventPublisher.java
│   │       │   └── config/AppConfig.java
│   │       └── resources/
│   │           ├── application.yml
│   │           ├── log4j2-spring.xml
│   │           └── db/migration/
│   │               ├── V0001__bootstrap.sql
│   │               ├── V0010__user_mgmt.sql
│   │               ├── V0020__portfolio.sql
│   │               ├── V0030__vdr_workflow_search.sql
│   │               ├── V0040__audit.sql
│   │               └── V0060__seed_data.sql
│   ├── user-auth/
│   │   ├── pom.xml
│   │   └── src/main/
│   │       ├── java/com/customer/can/userauth/
│   │       │   ├── UserAuthApplication.java
│   │       │   ├── domain/AppUser.java
│   │       │   ├── domain/Company.java
│   │       │   ├── service/UserService.java
│   │       │   ├── service/JwtService.java
│   │       │   ├── api/UserController.java
│   │       │   ├── api/AuthController.java
│   │       │   └── config/SecurityConfig.java
│   │       └── resources/application.yml
│   ├── vdr-ingestion/
│   │   ├── pom.xml
│   │   └── src/main/
│   │       ├── java/com/customer/can/vdr/
│   │       │   ├── VdrIngestionApplication.java
│   │       │   ├── domain/Document.java
│   │       │   ├── service/DocumentExtractor.java
│   │       │   ├── service/DocumentService.java
│   │       │   ├── api/DocumentController.java
│   │       │   └── messaging/DocumentEventPublisher.java
│   │       └── resources/application.yml
│   ├── workflow/
│   │   ├── pom.xml
│   │   └── src/main/
│   │       ├── java/com/customer/can/workflow/
│   │       │   ├── WorkflowApplication.java
│   │       │   ├── domain/AllocationWorkflow.java
│   │       │   ├── service/AllocationWorkflowService.java
│   │       │   ├── api/WorkflowController.java
│   │       │   └── messaging/WorkflowEventListener.java
│   │       └── resources/application.yml
│   ├── search/
│   │   ├── pom.xml
│   │   └── src/main/
│   │       ├── java/com/customer/can/search/
│   │       │   ├── SearchApplication.java
│   │       │   ├── service/SearchService.java
│   │       │   ├── api/SearchController.java
│   │       │   └── messaging/SearchIndexListener.java
│   │       └── resources/application.yml
│   └── webapp-bff/
│       ├── pom.xml
│       └── src/main/
│           ├── java/com/customer/can/bff/
│           │   ├── WebAppBffApplication.java
│           │   ├── api/BffPortfolioController.java
│           │   ├── api/BffSearchController.java
│           │   └── config/BffConfig.java
│           └── resources/application.yml
├── 00-frontend/
│   ├── index.html
│   ├── app.js
│   ├── style.css
│   ├── nginx.conf
│   └── Dockerfile
├── kubernetes/
│   ├── kustomization.yaml
│   ├── 00-namespace/namespace.yaml
│   ├── 10-infrastructure/
│   │   ├── oracle-secret.yaml
│   │   ├── oracle-statefulset.yaml
│   │   ├── activemq-deployment.yaml
│   │   └── logging/
│   │       ├── elasticsearch-statefulset.yaml
│   │       ├── filebeat-daemonset.yaml
│   │       └── kibana-deployment.yaml
│   ├── 20-services/
│   │   ├── property-allocation.yaml
│   │   ├── user-auth.yaml
│   │   ├── vdr-ingestion.yaml
│   │   ├── workflow.yaml
│   │   ├── search.yaml
│   │   ├── webapp-bff.yaml
│   │   └── frontend.yaml
│   └── 30-ingress/
│       └── ingress.yaml
└── terraform/
    ├── versions.tf
    ├── variables.tf
    ├── main.tf
    ├── outputs.tf
    └── modules/
        ├── aks/
        │   ├── main.tf
        │   ├── variables.tf
        │   └── outputs.tf
        ├── acr/
        │   ├── main.tf
        │   ├── variables.tf
        │   └── outputs.tf
        └── networking/
            ├── main.tf
            ├── variables.tf
            └── outputs.tf
```

## KEY IMPLEMENTATION REQUIREMENTS

### Java / Spring Boot
- **Java source/target: 1.8** in all pom.xml compiler configs
- **Spring Boot parent: 2.7.18**
- All services are standalone Spring Boot JARs
- Each service has its own `application.yml` with profile `local` that disables security (same local dev pattern as modern app)
- **NO Lombok** — use plain Java getters/setters
- Each service has a `CorrelationIdFilter` that reads `X-Correlation-Id` header, generates UUID if absent, puts it in Log4j2 MDC, passes it downstream

### Log4j2 JSON Logging (CRITICAL)
Every service must use **Log4j2** (NOT Logback). Add to every service pom.xml:
```xml
<dependency>
  <groupId>org.springframework.boot</groupId>
  <artifactId>spring-boot-starter-log4j2</artifactId>
</dependency>
```
And exclude Logback:
```xml
<dependency>
  <groupId>org.springframework.boot</groupId>
  <artifactId>spring-boot-starter</artifactId>
  <exclusions>
    <exclusion>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-logging</artifactId>
    </exclusion>
  </exclusions>
</dependency>
```

Each service has `src/main/resources/log4j2-spring.xml`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Configuration status="WARN">
  <Appenders>
    <Console name="Console" target="SYSTEM_OUT">
      <JsonLayout complete="false" compact="true" eventEol="true" includeTimeMillis="true">
        <KeyValuePair key="service" value="${env:SERVICE_NAME:-unknown}"/>
        <KeyValuePair key="environment" value="${env:ENVIRONMENT:-local}"/>
      </JsonLayout>
    </Console>
  </Appenders>
  <Loggers>
    <Root level="INFO">
      <AppenderRef ref="Console"/>
    </Root>
    <Logger name="com.customer.can" level="DEBUG" additivity="false">
      <AppenderRef ref="Console"/>
    </Logger>
  </Loggers>
</Configuration>
```

The MDC fields `correlationId`, `userId`, `portfolioId` must appear in every log line via the CorrelationIdFilter.

### Oracle Database
- Use `gvenzl/oracle-xe:21-slim` in Docker Compose (Oracle XE, SQL compatible with Oracle 10g dialect)
- Hibernate dialect: `org.hibernate.dialect.Oracle10gDialect`
- Flyway Oracle-compatible SQL (no PostgreSQL syntax — use `VARCHAR2`, `NUMBER`, `CLOB`, `SYSDATE`, sequences + triggers for auto-increment)
- Oracle SQL must NOT use `SERIAL`, `BOOLEAN`, `UUID` types — use `NUMBER(1)` for booleans, `VARCHAR2(36)` for UUIDs, `CHAR(36)` is also fine
- Auto-increment via sequences: `CREATE SEQUENCE portfolio_seq START WITH 1 INCREMENT BY 1` + `CREATE OR REPLACE TRIGGER portfolio_bir BEFORE INSERT ON portfolio FOR EACH ROW BEGIN IF :NEW.id IS NULL THEN SELECT portfolio_seq.NEXTVAL INTO :NEW.id FROM DUAL; END IF; END;`
- Use Oracle `VARCHAR2(4000)` for text, `NUMBER(18,2)` for money, `TIMESTAMP` for dates

### Flyway Oracle SQL (V0020__portfolio.sql example):
```sql
CREATE TABLE portfolio (
  id VARCHAR2(36) DEFAULT SYS_GUID() PRIMARY KEY,
  name VARCHAR2(255) NOT NULL,
  description CLOB,
  status VARCHAR2(50) DEFAULT 'OPEN' NOT NULL,
  cut_off_date DATE,
  final_bid_date DATE,
  project_phase VARCHAR2(50),
  created_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  created_by VARCHAR2(36),
  updated_at TIMESTAMP DEFAULT SYSTIMESTAMP,
  correlation_id VARCHAR2(36)
);

CREATE TABLE property (
  id VARCHAR2(36) DEFAULT SYS_GUID() PRIMARY KEY,
  portfolio_id VARCHAR2(36) NOT NULL REFERENCES portfolio(id),
  name VARCHAR2(255) NOT NULL,
  address VARCHAR2(500),
  city VARCHAR2(100),
  postcode VARCHAR2(20),
  property_type VARCHAR2(50),
  status VARCHAR2(50) DEFAULT 'PENDING',
  created_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL
);

CREATE TABLE property_valuation (
  id VARCHAR2(36) DEFAULT SYS_GUID() PRIMARY KEY,
  property_id VARCHAR2(36) NOT NULL REFERENCES property(id),
  portfolio_id VARCHAR2(36) NOT NULL REFERENCES portfolio(id),
  valuation_amount NUMBER(18,2),
  valuation_date DATE,
  valuer_company_id VARCHAR2(36),
  status VARCHAR2(50) DEFAULT 'PENDING',
  created_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL
);

CREATE TABLE broker_allocation (
  id VARCHAR2(36) DEFAULT SYS_GUID() PRIMARY KEY,
  property_id VARCHAR2(36) NOT NULL REFERENCES property(id),
  portfolio_id VARCHAR2(36) NOT NULL REFERENCES portfolio(id),
  broker_company_id VARCHAR2(36),
  assigned_at TIMESTAMP,
  status VARCHAR2(50) DEFAULT 'PENDING'
);

CREATE TABLE property_journal (
  id VARCHAR2(36) DEFAULT SYS_GUID() PRIMARY KEY,
  portfolio_id VARCHAR2(36) NOT NULL REFERENCES portfolio(id),
  entity_type VARCHAR2(100),
  entity_id VARCHAR2(36),
  event_type VARCHAR2(100),
  payload CLOB,
  correlation_id VARCHAR2(36),
  created_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  created_by VARCHAR2(100)
);
```

### ActiveMQ / JMS
- ActiveMQ 5.x in docker-compose: `apache/activemq-classic:5.18.3`
- Spring JMS with `@JmsListener` and `JmsTemplate`
- Topics: `portfolio.events`, `vdr.events`, `workflow.events`
- Dead-letter queue: `ActiveMQ.DLQ`
- `JmsEnvelope` POJO with: `messageId`, `correlationId`, `eventType`, `context`, `payload` (JSON string), `timestamp`

### Security (user-auth service)
- Spring Security 5.x (included in Spring Boot 2.7)
- JWT via `io.jsonwebtoken:jjwt:0.9.1`
- `SECRET_KEY` env var for signing
- No Azure AD — local username/password stored in Oracle (BCrypt hashed)
- All other services in `local` profile bypass auth via a pre-auth filter (same as modern app pattern)
- Production profile validates Bearer JWT from user-auth service

### Seed data (V0060__seed_data.sql)
Same companies and users as modern app:
- Companies: Beyond Capital (INTERNAL), Summit Brokers Ltd (BROKER), Apex Valuers Ltd (VALUER), First National Lender (LENDER)
- Users: Alice Admin (alice@beyondcapital.local / PORTFOLIO_ADMIN), Bob Broker (bob@summitbrokers.local / BROKER), Carol Valuer (carol@apexvaluers.local / VALUER), Dave Viewer (dave@beyondcapital.local / VIEWER), Eva SysAdmin (eva@beyondcapital.local / SYS_ADMIN). Passwords BCrypt hashed from `password123`.
- Portfolios: London Commercial Portfolio 2025 (OPEN, 3 properties), Manchester Industrial Portfolio (BIDDING, 2 properties)

### Docker Compose (docker-compose.local.yml)
```yaml
version: '3.8'
services:
  oracle-db:
    image: gvenzl/oracle-xe:21-slim
    environment:
      ORACLE_PASSWORD: Oracle_123
      APP_USER: canapp
      APP_USER_PASSWORD: canapp123
    ports: ["1521:1521"]
    volumes: [oracle-data:/opt/oracle/oradata]
    healthcheck:
      test: ["CMD", "healthcheck.sh"]
      interval: 30s
      timeout: 20s
      retries: 10

  activemq:
    image: apache/activemq-classic:5.18.3
    ports: ["61616:61616", "8161:8161"]

  elasticsearch:
    image: elasticsearch:7.17.0
    environment:
      discovery.type: single-node
      ES_JAVA_OPTS: "-Xms512m -Xmx512m"
    ports: ["9200:9200"]

  kibana:
    image: kibana:7.17.0
    ports: ["5601:5601"]
    depends_on: [elasticsearch]

  filebeat:
    image: elastic/filebeat:7.17.0
    user: root
    volumes:
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./docker/filebeat/filebeat.yml:/usr/share/filebeat/filebeat.yml:ro
    depends_on: [elasticsearch]

  db-migrate:
    image: flyway/flyway:9-alpine
    command: migrate
    environment:
      FLYWAY_URL: jdbc:oracle:thin:@oracle-db:1521/XEPDB1
      FLYWAY_USER: canapp
      FLYWAY_PASSWORD: canapp123
    volumes:
      - ./can-portfolio-legacy-app/property-allocation/src/main/resources/db/migration:/flyway/sql
    depends_on:
      oracle-db:
        condition: service_healthy

  property-allocation:
    build:
      context: ./can-portfolio-legacy-app
      dockerfile: Dockerfile
      args: SERVICE=property-allocation
    environment:
      SPRING_PROFILES_ACTIVE: local
      SPRING_DATASOURCE_URL: jdbc:oracle:thin:@oracle-db:1521/XEPDB1
      SPRING_DATASOURCE_USERNAME: canapp
      SPRING_DATASOURCE_PASSWORD: canapp123
      SPRING_ACTIVEMQ_BROKER_URL: tcp://activemq:61616
      SERVICE_NAME: property-allocation
    ports: ["8002:8002"]
    depends_on: [oracle-db, activemq]

  user-auth:
    build:
      context: ./can-portfolio-legacy-app
      dockerfile: Dockerfile
      args: SERVICE=user-auth
    environment:
      SPRING_PROFILES_ACTIVE: local
      SPRING_DATASOURCE_URL: jdbc:oracle:thin:@oracle-db:1521/XEPDB1
      SPRING_DATASOURCE_USERNAME: canapp
      SPRING_DATASOURCE_PASSWORD: canapp123
      JWT_SECRET: local-dev-secret-key-32chars-min
      SERVICE_NAME: user-auth
    ports: ["8001:8001"]
    depends_on: [oracle-db]

  vdr-ingestion:
    build:
      context: ./can-portfolio-legacy-app
      dockerfile: Dockerfile
      args: SERVICE=vdr-ingestion
    environment:
      SPRING_PROFILES_ACTIVE: local
      SPRING_DATASOURCE_URL: jdbc:oracle:thin:@oracle-db:1521/XEPDB1
      SPRING_DATASOURCE_USERNAME: canapp
      SPRING_DATASOURCE_PASSWORD: canapp123
      SPRING_ACTIVEMQ_BROKER_URL: tcp://activemq:61616
      SERVICE_NAME: vdr-ingestion
    ports: ["8003:8003"]
    depends_on: [oracle-db, activemq]

  workflow:
    build:
      context: ./can-portfolio-legacy-app
      dockerfile: Dockerfile
      args: SERVICE=workflow
    environment:
      SPRING_PROFILES_ACTIVE: local
      SPRING_DATASOURCE_URL: jdbc:oracle:thin:@oracle-db:1521/XEPDB1
      SPRING_DATASOURCE_USERNAME: canapp
      SPRING_DATASOURCE_PASSWORD: canapp123
      SPRING_ACTIVEMQ_BROKER_URL: tcp://activemq:61616
      SERVICE_NAME: workflow
    ports: ["8004:8004"]
    depends_on: [oracle-db, activemq]

  search:
    build:
      context: ./can-portfolio-legacy-app
      dockerfile: Dockerfile
      args: SERVICE=search
    environment:
      SPRING_PROFILES_ACTIVE: local
      SPRING_DATASOURCE_URL: jdbc:oracle:thin:@oracle-db:1521/XEPDB1
      SPRING_DATASOURCE_USERNAME: canapp
      SPRING_DATASOURCE_PASSWORD: canapp123
      SERVICE_NAME: search
    ports: ["8005:8005"]
    depends_on: [oracle-db]

  webapp-bff:
    build:
      context: ./can-portfolio-legacy-app
      dockerfile: Dockerfile
      args: SERVICE=webapp-bff
    environment:
      SPRING_PROFILES_ACTIVE: local
      PROPERTY_ALLOCATION_URL: http://property-allocation:8002
      USER_AUTH_URL: http://user-auth:8001
      SEARCH_URL: http://search:8005
      SERVICE_NAME: webapp-bff
    ports: ["8080:8080"]
    depends_on: [property-allocation, user-auth, search]

  frontend:
    build: ./00-frontend
    ports: ["3000:80"]
    depends_on: [webapp-bff]

volumes:
  oracle-data:
```

### Dockerfile (multi-stage, one per service via ARG)
```dockerfile
FROM maven:3.8.8-eclipse-temurin-8 AS build
ARG SERVICE
WORKDIR /build
COPY pom.xml .
COPY common-domain/ common-domain/
COPY ${SERVICE}/ ${SERVICE}/
RUN mvn -pl common-domain,${SERVICE} -am package -DskipTests -q

FROM eclipse-temurin:8-jre-alpine
ARG SERVICE
WORKDIR /app
COPY --from=build /build/${SERVICE}/target/*.jar app.jar
RUN addgroup -S can && adduser -S can -G can
USER can
ENTRYPOINT ["java", "-jar", "app.jar"]
```

### Kubernetes Manifests
For each service, create a Deployment + Service YAML. Example for property-allocation:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: property-allocation
  namespace: can-legacy
spec:
  replicas: 2
  selector:
    matchLabels:
      app: property-allocation
  template:
    metadata:
      labels:
        app: property-allocation
    spec:
      containers:
      - name: property-allocation
        image: $(ACR_NAME).azurecr.io/can-legacy/property-allocation:latest
        ports:
        - containerPort: 8002
        env:
        - name: SPRING_PROFILES_ACTIVE
          value: prod
        - name: SERVICE_NAME
          value: property-allocation
        - name: ENVIRONMENT
          value: production
        - name: SPRING_DATASOURCE_URL
          valueFrom:
            secretKeyRef:
              name: oracle-secret
              key: jdbc-url
        - name: SPRING_DATASOURCE_USERNAME
          valueFrom:
            secretKeyRef:
              name: oracle-secret
              key: username
        - name: SPRING_DATASOURCE_PASSWORD
          valueFrom:
            secretKeyRef:
              name: oracle-secret
              key: password
        - name: SPRING_ACTIVEMQ_BROKER_URL
          value: tcp://activemq:61616
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "1Gi"
            cpu: "500m"
        readinessProbe:
          httpGet:
            path: /actuator/health
            port: 8002
          initialDelaySeconds: 60
          periodSeconds: 10
        livenessProbe:
          httpGet:
            path: /actuator/health
            port: 8002
          initialDelaySeconds: 90
          periodSeconds: 15
---
apiVersion: v1
kind: Service
metadata:
  name: property-allocation
  namespace: can-legacy
spec:
  selector:
    app: property-allocation
  ports:
  - port: 8002
    targetPort: 8002
```

### Filebeat DaemonSet (Kubernetes log collection)
Filebeat collects stdout logs from all containers and ships to Elasticsearch:
```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: filebeat
  namespace: can-legacy
spec:
  selector:
    matchLabels:
      app: filebeat
  template:
    metadata:
      labels:
        app: filebeat
    spec:
      serviceAccountName: filebeat
      containers:
      - name: filebeat
        image: elastic/filebeat:7.17.21
        args: ["-c", "/etc/filebeat.yml", "-e"]
        env:
        - name: ELASTICSEARCH_HOST
          value: elasticsearch
        - name: ELASTICSEARCH_PORT
          value: "9200"
        volumeMounts:
        - name: config
          mountPath: /etc/filebeat.yml
          subPath: filebeat.yml
        - name: varlog
          mountPath: /var/log
        - name: varlibdockercontainers
          mountPath: /var/lib/docker/containers
          readOnly: true
      volumes:
      - name: config
        configMap:
          name: filebeat-config
      - name: varlog
        hostPath:
          path: /var/log
      - name: varlibdockercontainers
        hostPath:
          path: /var/lib/docker/containers
```

### Terraform (Azure AKS)
`terraform/main.tf`:
```hcl
terraform {
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 3.0" }
    kubernetes = { source = "hashicorp/kubernetes", version = "~> 2.0" }
  }
  backend "azurerm" {
    resource_group_name  = "can-legacy-tfstate-rg"
    storage_account_name = "canlegacytfstate"
    container_name       = "tfstate"
    key                  = "can-legacy.terraform.tfstate"
  }
}

provider "azurerm" { features {} }

module "networking" {
  source              = "./modules/networking"
  resource_group_name = var.resource_group_name
  location            = var.location
  vnet_cidr           = var.vnet_cidr
  aks_subnet_cidr     = var.aks_subnet_cidr
}

module "acr" {
  source              = "./modules/acr"
  resource_group_name = var.resource_group_name
  location            = var.location
  acr_name            = var.acr_name
  sku                 = "Standard"
}

module "aks" {
  source              = "./modules/aks"
  resource_group_name = var.resource_group_name
  location            = var.location
  cluster_name        = var.cluster_name
  kubernetes_version  = "1.28"
  subnet_id           = module.networking.aks_subnet_id
  acr_id              = module.acr.acr_id
  node_count          = var.node_count
  vm_size             = var.vm_size
}
```

`terraform/modules/aks/main.tf`:
```hcl
resource "azurerm_kubernetes_cluster" "aks" {
  name                = var.cluster_name
  location            = var.location
  resource_group_name = var.resource_group_name
  dns_prefix          = "${var.cluster_name}-dns"
  kubernetes_version  = var.kubernetes_version

  default_node_pool {
    name           = "system"
    node_count     = var.node_count
    vm_size        = var.vm_size
    vnet_subnet_id = var.subnet_id
    os_disk_size_gb = 50
  }

  identity { type = "SystemAssigned" }

  network_profile {
    network_plugin    = "azure"
    load_balancer_sku = "standard"
    outbound_type     = "loadBalancer"
  }

  oms_agent {
    log_analytics_workspace_id = azurerm_log_analytics_workspace.law.id
  }

  tags = { environment = "production", app = "can-legacy" }
}

resource "azurerm_log_analytics_workspace" "law" {
  name                = "${var.cluster_name}-law"
  location            = var.location
  resource_group_name = var.resource_group_name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                = var.acr_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_kubernetes_cluster.aks.kubelet_identity[0].object_id
}

resource "azurerm_role_assignment" "aks_network" {
  scope                = var.subnet_id
  role_definition_name = "Network Contributor"
  principal_id         = azurerm_kubernetes_cluster.aks.identity[0].principal_id
}
```

## SPECIFIC JAVA CODE TO WRITE

### parent pom.xml
```xml
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.customer.can</groupId>
  <artifactId>can-portfolio-legacy</artifactId>
  <version>1.0.0-SNAPSHOT</version>
  <packaging>pom</packaging>

  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>2.7.18</version>
  </parent>

  <modules>
    <module>common-domain</module>
    <module>property-allocation</module>
    <module>user-auth</module>
    <module>vdr-ingestion</module>
    <module>workflow</module>
    <module>search</module>
    <module>webapp-bff</module>
  </modules>

  <properties>
    <java.version>1.8</java.version>
    <maven.compiler.source>1.8</maven.compiler.source>
    <maven.compiler.target>1.8</maven.compiler.target>
    <jjwt.version>0.9.1</jjwt.version>
    <tika.version>1.28.5</tika.version>
    <springfox.version>3.0.0</springfox.version>
  </properties>

  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>com.customer.can</groupId>
        <artifactId>common-domain</artifactId>
        <version>${project.version}</version>
      </dependency>
      <dependency>
        <groupId>io.jsonwebtoken</groupId>
        <artifactId>jjwt</artifactId>
        <version>${jjwt.version}</version>
      </dependency>
      <dependency>
        <groupId>org.apache.tika</groupId>
        <artifactId>tika-core</artifactId>
        <version>${tika.version}</version>
      </dependency>
      <dependency>
        <groupId>org.apache.tika</groupId>
        <artifactId>tika-parsers</artifactId>
        <version>${tika.version}</version>
      </dependency>
      <dependency>
        <groupId>io.springfox</groupId>
        <artifactId>springfox-boot-starter</artifactId>
        <version>${springfox.version}</version>
      </dependency>
    </dependencies>
  </dependencyManagement>
</project>
```

### CorrelationIdFilter.java (in common-domain, included in every service)
```java
package com.customer.can.common.filter;

import org.apache.logging.log4j.ThreadContext;
import javax.servlet.*;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.UUID;

public class CorrelationIdFilter implements Filter {
    public static final String CORRELATION_HEADER = "X-Correlation-Id";
    public static final String MDC_KEY = "correlationId";

    @Override
    public void doFilter(ServletRequest request, ServletResponse response, FilterChain chain)
            throws IOException, ServletException {
        HttpServletRequest httpRequest = (HttpServletRequest) request;
        String correlationId = httpRequest.getHeader(CORRELATION_HEADER);
        if (correlationId == null || correlationId.isEmpty()) {
            correlationId = UUID.randomUUID().toString();
        }
        ThreadContext.put(MDC_KEY, correlationId);
        ((HttpServletResponse) response).setHeader(CORRELATION_HEADER, correlationId);
        try {
            chain.doFilter(request, response);
        } finally {
            ThreadContext.remove(MDC_KEY);
        }
    }
}
```

### Portfolio.java JPA entity
```java
package com.customer.can.property.domain;

import javax.persistence.*;
import java.math.BigDecimal;
import java.util.Date;
import java.util.List;

@Entity
@Table(name = "PORTFOLIO")
public class Portfolio {
    @Id
    @Column(name = "ID", length = 36)
    private String id;
    
    @Column(name = "NAME", nullable = false, length = 255)
    private String name;
    
    @Column(name = "DESCRIPTION", columnDefinition = "CLOB")
    private String description;
    
    @Column(name = "STATUS", length = 50)
    private String status = "OPEN";
    
    @Column(name = "CUT_OFF_DATE")
    @Temporal(TemporalType.DATE)
    private Date cutOffDate;
    
    @Column(name = "FINAL_BID_DATE")
    @Temporal(TemporalType.DATE)
    private Date finalBidDate;
    
    @Column(name = "PROJECT_PHASE", length = 50)
    private String projectPhase;
    
    @Column(name = "CREATED_AT")
    @Temporal(TemporalType.TIMESTAMP)
    private Date createdAt;
    
    @Column(name = "CREATED_BY", length = 36)
    private String createdBy;
    
    @OneToMany(mappedBy = "portfolio", fetch = FetchType.LAZY, cascade = CascadeType.ALL)
    private List<Property> properties;
    
    @PrePersist
    public void prePersist() {
        if (this.id == null) {
            this.id = java.util.UUID.randomUUID().toString();
        }
        this.createdAt = new Date();
    }
    
    // getters and setters for all fields
    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public String getDescription() { return description; }
    public void setDescription(String description) { this.description = description; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public Date getCutOffDate() { return cutOffDate; }
    public void setCutOffDate(Date cutOffDate) { this.cutOffDate = cutOffDate; }
    public Date getFinalBidDate() { return finalBidDate; }
    public void setFinalBidDate(Date finalBidDate) { this.finalBidDate = finalBidDate; }
    public String getProjectPhase() { return projectPhase; }
    public void setProjectPhase(String projectPhase) { this.projectPhase = projectPhase; }
    public Date getCreatedAt() { return createdAt; }
    public void setCreatedAt(Date createdAt) { this.createdAt = createdAt; }
    public String getCreatedBy() { return createdBy; }
    public void setCreatedBy(String createdBy) { this.createdBy = createdBy; }
    public List<Property> getProperties() { return properties; }
    public void setProperties(List<Property> properties) { this.properties = properties; }
}
```

### PortfolioController.java
```java
package com.customer.can.property.api;

import com.customer.can.property.domain.Portfolio;
import com.customer.can.property.service.PortfolioService;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.apache.logging.log4j.ThreadContext;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import java.util.List;

@RestController
@RequestMapping("/api/v1/portfolios")
public class PortfolioController {
    private static final Logger log = LogManager.getLogger(PortfolioController.class);
    
    private final PortfolioService portfolioService;
    
    public PortfolioController(PortfolioService portfolioService) {
        this.portfolioService = portfolioService;
    }
    
    @GetMapping
    public ResponseEntity<List<Portfolio>> listPortfolios() {
        log.info("{\"action\":\"list_portfolios\",\"correlationId\":\"{}\"}", 
                 ThreadContext.get("correlationId"));
        return ResponseEntity.ok(portfolioService.findAll());
    }
    
    @GetMapping("/{id}")
    public ResponseEntity<Portfolio> getPortfolio(@PathVariable String id) {
        log.info("{\"action\":\"get_portfolio\",\"portfolioId\":\"{}\",\"correlationId\":\"{}\"}", 
                 id, ThreadContext.get("correlationId"));
        return portfolioService.findById(id)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }
    
    @PostMapping
    public ResponseEntity<Portfolio> createPortfolio(@RequestBody Portfolio portfolio) {
        log.info("{\"action\":\"create_portfolio\",\"name\":\"{}\",\"correlationId\":\"{}\"}", 
                 portfolio.getName(), ThreadContext.get("correlationId"));
        Portfolio created = portfolioService.create(portfolio);
        return ResponseEntity.status(201).body(created);
    }
    
    @PutMapping("/{id}/close")
    public ResponseEntity<Portfolio> closePortfolio(@PathVariable String id) {
        log.info("{\"action\":\"close_portfolio\",\"portfolioId\":\"{}\",\"correlationId\":\"{}\"}", 
                 id, ThreadContext.get("correlationId"));
        return ResponseEntity.ok(portfolioService.close(id));
    }
}
```

### application.yml for property-allocation
```yaml
server:
  port: 8002

spring:
  application:
    name: property-allocation
  datasource:
    url: ${SPRING_DATASOURCE_URL:jdbc:oracle:thin:@localhost:1521/XEPDB1}
    username: ${SPRING_DATASOURCE_USERNAME:canapp}
    password: ${SPRING_DATASOURCE_PASSWORD:canapp123}
    driver-class-name: oracle.jdbc.OracleDriver
  jpa:
    database-platform: org.hibernate.dialect.Oracle10gDialect
    hibernate:
      ddl-auto: validate
    show-sql: false
  flyway:
    enabled: true
    locations: classpath:db/migration
    baseline-on-migrate: true
  activemq:
    broker-url: ${SPRING_ACTIVEMQ_BROKER_URL:tcp://localhost:61616}
    user: admin
    password: admin

management:
  endpoints:
    web:
      exposure:
        include: health,info,metrics
  endpoint:
    health:
      show-details: always

logging:
  config: classpath:log4j2-spring.xml

---
spring:
  config:
    activate:
      on-profile: local
  autoconfigure:
    exclude:
      - org.springframework.boot.autoconfigure.security.servlet.SecurityAutoConfiguration
```

Now write ALL the files. Create real, complete, working Java 8 code — not stubs or placeholders. Every .java file must compile. Every SQL migration must be valid Oracle SQL. All YAML must be valid.

Make sure to create a `docker/filebeat/filebeat.yml` for the docker-compose filebeat config:
```yaml
filebeat.autodiscover:
  providers:
    - type: docker
      hints.enabled: true
      hints.default_config:
        type: container
        paths:
          - /var/lib/docker/containers/${data.container.id}/*.log

processors:
  - add_docker_metadata: ~
  - decode_json_fields:
      fields: ["message"]
      target: "json"
      overwrite_keys: true

output.elasticsearch:
  hosts: ["elasticsearch:9200"]
  index: "can-legacy-logs-%{+yyyy.MM.dd}"

setup.kibana:
  host: "kibana:5601"
```

Also create `kubernetes/10-infrastructure/logging/filebeat-config.yaml` as a ConfigMap with the Kubernetes filebeat config that reads container logs from `/var/log/containers/*.log`.

Write all Terraform module files completely with proper HCL syntax.

IMPORTANT:
- Write ALL files — don't leave any file as "TODO" or skeleton
- All Java code must have proper imports
- All pom.xml files must have the ojdbc dependency from Maven Central: `com.oracle.database.jdbc:ojdbc8:21.7.0.0`
- The webapp-bff must expose Swagger UI at http://localhost:8080/swagger-ui/ with all REST endpoints documented
- The README.md must explain: quick start, endpoints table, tech stack comparison table (modern vs legacy), and how to run on K8s

Start writing files now. Create everything under `examples/java-springboot-legacy-app/`.