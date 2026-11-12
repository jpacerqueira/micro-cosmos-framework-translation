FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GOOGLE_GENAI_USE_VERTEXAI=TRUE \
    DOTNET_ROOT=/usr/share/dotnet \
    GRADLE_HOME=/opt/gradle-9.6.1 \
    MAVEN_HOME=/opt/apache-maven-3.9.9
ENV PATH="${PATH}:${DOTNET_ROOT}:${GRADLE_HOME}/bin:${MAVEN_HOME}/bin"

# .NET SDK is needed so `dotnet restore --use-lock-file` can generate
# packages.lock.json before Trivy scans C# output — without it Trivy only
# sees direct <PackageReference> names, not the full transitive dependency
# graph (see micro_cosmos/tools/security_tools.py's _maybe_restore_dotnet_lockfile).
# If this fails to run with a globalization/ICU error on a minimal Debian
# image, install libicu72 via apt or set
# DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=true — not pre-emptively added here
# since it's not yet confirmed to be needed on this base image.
#
# JDK + Gradle CLI are needed so Trivy can see Gradle-based Java/Kotlin
# dependencies at all — Trivy does not read build.gradle/.kts directly,
# only gradle.lockfile, and a project without one gets zero Trivy detection
# (worse than Maven's pom.xml, which Trivy reads with no build step). See
# _maybe_restore_jvm_lockfile() in security_tools.py.
#
# Maven is installed so `mvn` is available for real test execution of
# generated Java/Maven seams, via the Test Agent's sandboxed subprocess
# (micro_cosmos/tools/fitness_runner.py). Trivy's own narrower Maven gap
# (unresolved pom.xml version properties without a full `mvn dependency:tree`)
# is unrelated and still unaddressed — installing Maven here does not fix
# that.
#
# gnucobol4 gives us a real `cobc` compiler/runtime — needed to actually
# compile and run a source estate's *original* COBOL to produce golden
# reference output (stdout/output files) for differential/golden-master
# testing against the translated target-language output. Without this,
# "equivalence" for a COBOL estate can only be judged by code review, not
# proven by running both versions against the same input and diffing.
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs curl ca-certificates unzip openjdk-21-jdk-headless gnucobol4 \
 && curl -sfL https://github.com/aquasecurity/trivy/releases/download/v0.70.0/trivy_0.70.0_Linux-64bit.tar.gz \
    | tar -xz -C /usr/local/bin trivy \
 && curl -sSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh \
 && chmod +x /tmp/dotnet-install.sh \
 && /tmp/dotnet-install.sh --channel LTS --install-dir "${DOTNET_ROOT}" \
 # The SDK install above only bundles ITS OWN "LTS" runtime (.NET 10 as of
 # this writing) — but coder_tools.py's C# scaffold hardcodes
 # <TargetFramework>net8.0</TargetFramework>, and a test host refuses to run
 # a net8.0 build against a newer-only runtime ("You must install or update
 # .NET to run this application"). Confirmed via a real container run: every
 # C# test execution failed outright until this was added. Install the
 # net8.0 runtime specifically, alongside whatever the SDK itself bundles.
 && /tmp/dotnet-install.sh --runtime dotnet --channel 8.0 --install-dir "${DOTNET_ROOT}" \
 && rm /tmp/dotnet-install.sh \
 && curl -fsSL -o /tmp/gradle.zip https://services.gradle.org/distributions/gradle-9.6.1-bin.zip \
 && unzip -q /tmp/gradle.zip -d /opt \
 && rm /tmp/gradle.zip \
 && curl -fsSL -o /tmp/maven.tar.gz https://archive.apache.org/dist/maven/maven-3/3.9.9/binaries/apache-maven-3.9.9-bin.tar.gz \
 && tar -xzf /tmp/maven.tar.gz -C /opt \
 && rm /tmp/maven.tar.gz \
 && rm -rf /var/lib/apt/lists/*

# Unprivileged identity the Test Agent drops into for real test-execution
# subprocesses only (micro_cosmos/tools/fitness_runner.py's _sandbox_preexec) —
# the app itself still runs as root. UID must match _SANDBOX_UID there.
#
# --create-home (not --no-create-home) is required, not just tidy: confirmed
# via a real container run that Java/Maven resolve `user.home` from the
# passwd database entry for the current UID, not from the $HOME env var —
# so without a real home directory on disk, every Maven-based test execution
# fails outright with "Could not create local repository at
# /home/sandboxrunner/.m2/repository". This also means Maven's dependency
# cache is warm and persists across seams/TDD iterations within the same
# container's lifetime, rather than re-downloading from Maven Central every
# single time.
RUN useradd --create-home --shell /usr/sbin/nologin --uid 10001 sandboxrunner

WORKDIR /app
COPY pyproject.toml /app/
COPY micro_cosmos /app/micro_cosmos
COPY scripts /app/scripts
COPY tests /app/tests
# Real example estates the test suite exercises directly (COBOL, Databricks,
# NATS, CQRS, etc. fixtures under examples/*) — confirmed missing via a real
# container run: without this, ~30 tests fail with FileNotFoundError-shaped
# errors that look like real bugs but are actually just an absent fixture
# tree. Live pipeline runs never surfaced this because they mount examples/
# in as a volume (`-v .../examples:/app/examples:ro`), which papers over a
# missing COPY at build time.
COPY examples /app/examples
COPY docker-compose.yml /app/docker-compose.yml
COPY llm-gateway /app/llm-gateway
RUN pip install --no-cache-dir . \
 && pip install --no-cache-dir "pytest>=8" "pytest-asyncio>=0.23"

EXPOSE 8080
CMD ["uvicorn", "micro_cosmos.web.app:app", "--host", "0.0.0.0", "--port", "8080"]
