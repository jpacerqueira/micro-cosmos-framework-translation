# ── Stage 1: build ────────────────────────────────────────────────────────────
FROM maven:3.9-eclipse-temurin-8 AS build
WORKDIR /build

# Cache the dependency layer separately from the source layer
COPY pom.xml .
RUN mvn dependency:go-offline -q

COPY src ./src

# Runs the full Cucumber BDD suite (H2 + embedded ActiveMQ — see
# application-test.properties) and the Jacoco coverage gate before packaging.
# A failing test or a coverage drop below 80% on the scoring engine fails the
# image build — this is the "100% accurate build" gate. Reports are kept in
# this intermediate layer at /build/target/{surefire-reports,cucumber-report,site/jacoco}
# and can be pulled out with `docker compose run --rm tests` (see docker-compose.yml),
# which bind-mounts the repo so the same reports land on the host.
RUN mvn -B clean verify

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM eclipse-temurin:8-jre-jammy
WORKDIR /app

COPY --from=build /build/target/bankxyz-fraud-detection-*.jar app.jar

EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
