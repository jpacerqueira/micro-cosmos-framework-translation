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
