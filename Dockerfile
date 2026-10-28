FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /workspace
COPY pom.xml .
COPY src ./src

# Maven Central 直连在境内网络慢且易超时，默认改走国内镜像，可用 build-arg 覆盖。
# 只缓存 repository 目录，避免 settings.xml 被 cache mount 遮蔽。
ARG MAVEN_MIRROR_URL=https://maven.aliyun.com/repository/public
RUN mkdir -p /root/.m2 && \
    if [ -n "$MAVEN_MIRROR_URL" ]; then \
      printf '<settings><mirrors><mirror><id>central-mirror</id><mirrorOf>central</mirrorOf><url>%s</url></mirror></mirrors></settings>\n' "$MAVEN_MIRROR_URL" > /root/.m2/settings.xml; \
    fi

RUN --mount=type=cache,target=/root/.m2/repository mvn -B -DskipTests -Dmaven.wagon.http.retryHandler.count=3 package

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /workspace/target/*.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
