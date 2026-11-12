# =============================================================================
# NatWest Fraud Detection — Windows Container Dockerfile
# Requires Docker Desktop with Windows containers enabled.
#
# Build stage: MSBuild on Windows Server Core with .NET Framework SDK 4.8
# Runtime stage: IIS on Windows Server Core with ASP.NET 4.8
# =============================================================================

# --- Stage 1: Build ---
FROM mcr.microsoft.com/dotnet/framework/sdk:4.8-windowsservercore-ltsc2019 AS build

WORKDIR C:/src

# Copy solution and restore NuGet packages first (layer cache)
COPY NatWest.FraudDetection.sln .
COPY src/NatWest.FraudDetection.Web/packages.config src/NatWest.FraudDetection.Web/

RUN nuget restore NatWest.FraudDetection.sln

# Copy full source and build
COPY . .

RUN msbuild NatWest.FraudDetection.sln ^
    /p:Configuration=Release ^
    /p:DeployOnBuild=true ^
    /p:WebPublishMethod=FileSystem ^
    /p:PublishUrl=C:\out ^
    /p:DeleteExistingFiles=true ^
    /nologo /verbosity:minimal

# --- Stage 2: Runtime ---
FROM mcr.microsoft.com/dotnet/framework/aspnet:4.8-windowsservercore-ltsc2019 AS runtime

WORKDIR C:/inetpub/wwwroot

# Copy published web app from build stage
COPY --from=build C:/out .

# Override web.config connection string from environment variable
# (FRAUD_DB_CONNECTION is set by docker-compose)
RUN powershell -Command \
    "$config = [xml](Get-Content C:\inetpub\wwwroot\Web.config); \
     $env = [System.Environment]::GetEnvironmentVariable('FRAUD_DB_CONNECTION'); \
     if ($env) { \
       $node = $config.configuration.connectionStrings.add | Where-Object { $_.name -eq 'FraudDb' }; \
       $node.connectionString = $env; \
       $config.Save('C:\inetpub\wwwroot\Web.config') \
     }"

EXPOSE 80
