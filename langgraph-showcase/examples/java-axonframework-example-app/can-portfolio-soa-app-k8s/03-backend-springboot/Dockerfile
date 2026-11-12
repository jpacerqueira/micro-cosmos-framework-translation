# ── Stage 1: resolve dependencies (layer cached on pom changes only) ──────────
FROM maven:3.9-eclipse-temurin-21-alpine AS deps
WORKDIR /build
COPY pom.xml ./
COPY common-domain/pom.xml       common-domain/
COPY webapp-bff/pom.xml          webapp-bff/
COPY user-auth/pom.xml           user-auth/
COPY property-allocation/pom.xml property-allocation/
COPY vdr-ingestion/pom.xml       vdr-ingestion/
COPY workflow/pom.xml            workflow/
COPY search/pom.xml              search/
# --fail-at-end: local inter-module deps not in repo — that's expected, ignore exit code
RUN mvn dependency:go-offline -q --fail-at-end 2>/dev/null || true

# ── Stage 2: compile and package all modules ──────────────────────────────────
FROM deps AS builder
COPY common-domain/src       common-domain/src
COPY webapp-bff/src          webapp-bff/src
COPY user-auth/src           user-auth/src
COPY property-allocation/src property-allocation/src
COPY vdr-ingestion/src       vdr-ingestion/src
COPY workflow/src            workflow/src
COPY search/src              search/src
# -Dmaven.test.skip=true skips test compilation too (faster than -DskipTests)
RUN mvn -Dmaven.test.skip=true -q package

# ── Stage 3: minimal runtime image, one per service via --build-arg ───────────
FROM eclipse-temurin:21-jre-alpine
ARG MODULE
RUN addgroup -g 10001 -S app && adduser -u 10001 -S app -G app
COPY --from=builder /build/${MODULE}/target/*.jar /app/app.jar
RUN chown app:app /app/app.jar
USER 10001:10001
EXPOSE 8080 8081
ENTRYPOINT ["java", "-XX:+UseZGC", "-XX:MaxRAMPercentage=75", "-jar", "/app/app.jar"]
