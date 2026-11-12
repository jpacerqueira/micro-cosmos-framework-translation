# Azure Blob to Event Grid Function

This Azure Function automatically processes files uploaded to Azure Blob Storage and publishes their contents to Azure Event Grid topics. It's designed for scenarios where you need to trigger downstream processes when new files arrive in your storage account.

## Features

- Automatic blob processing on file upload
- Asynchronous event publishing to Event Grid
- Comprehensive error handling and logging
- Application Insights integration
- Configurable parallelism for blob processing
- Dependency injection for better testability
- Structured logging with different log levels

## Prerequisites

- Azure subscription
- Azure Storage Account
- Azure Event Grid Topic
- .NET 6.0 SDK
- Azure Functions Core Tools v4
- Visual Studio 2022 or VS Code with Azure Functions extension

## Architecture

```
[Azure Blob Storage] → [Azure Function] → [Azure Event Grid] → [Subscribers]
```

The function follows this flow:
1. New blob is uploaded to the input container
2. Function is triggered automatically
3. Blob content is read and processed
4. Event is published to Event Grid topic
5. Subscribers receive the event

## Configuration

### Required Settings

Update `local.settings.json` with your values:

```json
{
    "Values": {
        "BlobStorageConnection": "YOUR_BLOB_STORAGE_CONNECTION_STRING",
        "EventGridTopicEndpoint": "YOUR_EVENT_GRID_TOPIC_ENDPOINT",
        "EventGridTopicKey": "YOUR_EVENT_GRID_TOPIC_KEY",
        "APPINSIGHTS_INSTRUMENTATIONKEY": "YOUR_APP_INSIGHTS_KEY"
    }
}
```

### Host Configuration

The `host.json` file includes:
- Logging configuration
- Blob processing settings
- HTTP settings
- Function timeout
- Singleton behavior

## Local Development

1. Clone the repository
2. Update `local.settings.json` with your connection strings
3. Create the input container in your storage account
4. Run the function locally:
   ```bash
   func start
   ```

## Deployment

### Azure Portal

1. Create a new Function App
2. Configure Application Settings with your connection strings
3. Deploy using Azure Functions Core Tools:
   ```bash
   func azure functionapp publish <FunctionAppName>
   ```

### Azure DevOps Pipeline

```yaml
trigger:
  - main

pool:
  vmImage: 'ubuntu-latest'

steps:
- task: DotNetCoreCLI@2
  inputs:
    command: 'publish'
    publishWebProjects: false
    projects: '**/*.csproj'
    arguments: '--configuration Release --output $(Build.ArtifactStagingDirectory)'
    zipAfterPublish: true

- task: AzureFunctionApp@1
  inputs:
    azureSubscription: 'your-subscription'
    appName: 'your-function-app-name'
    package: '$(Build.ArtifactStagingDirectory)/**/*.zip'
```

## Event Schema

The function publishes events with this schema:

```json
{
    "id": "unique-event-id",
    "subject": "blobs/{blobName}",
    "eventType": "BlobCreated",
    "eventTime": "timestamp",
    "data": {
        "blobName": "name-of-blob",
        "content": "blob-content",
        "timestamp": "utc-timestamp"
    }
}
```

## Monitoring

### Application Insights

The function is configured with Application Insights for:
- Request tracking
- Exception monitoring
- Performance metrics
- Dependency tracking
- Live metrics

### Logging

Log levels are configured in `host.json`:
- Information: Default level
- Error: For exceptions
- Warning: For potential issues
- Debug: For detailed troubleshooting

## Error Handling

The function includes:
- Try-catch blocks for error handling
- Poison blob handling
- Retry policies for Event Grid publishing
- Detailed error logging

## Performance Considerations

- Blob processing is parallelized (max 4 concurrent operations)
- Event Grid client is singleton
- Stream reading is optimized
- Memory usage is monitored

## Security

- Connection strings are stored in Application Settings
- No hardcoded credentials
- CORS is configurable
- HTTPS is enforced in production

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For issues and feature requests, please create an issue in the repository.
