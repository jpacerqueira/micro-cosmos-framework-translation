using System;
using System.IO;
using System.Threading.Tasks;
using Microsoft.Azure.WebJobs;
using Microsoft.Azure.WebJobs.Host;
using Microsoft.Extensions.Logging;
using Azure.Messaging.EventGrid;
using Azure.Messaging.EventGrid.SystemEvents;
using Azure.Storage.Blobs;
using System.Text;

namespace BlobToEventGridFunction
{
    public class BlobToEventGridFunction
    {
        private readonly EventGridPublisherClient _eventGridClient;

        public BlobToEventGridFunction()
        {
            string topicEndpoint = Environment.GetEnvironmentVariable("EventGridTopicEndpoint");
            string topicKey = Environment.GetEnvironmentVariable("EventGridTopicKey");
            _eventGridClient = new EventGridPublisherClient(
                new Uri(topicEndpoint),
                new Azure.AzureKeyCredential(topicKey));
        }

        [FunctionName("BlobToEventGridFunction")]
        public async Task Run(
            [BlobTrigger("input-container/{name}", Connection = "BlobStorageConnection")] Stream blobStream,
            string name,
            ILogger log)
        {
            try
            {
                log.LogInformation($"Processing blob: {name}");

                // Read blob content
                using var reader = new StreamReader(blobStream);
                string content = await reader.ReadToEndAsync();

                // Create event data
                var eventData = new
                {
                    blobName = name,
                    content = content,
                    timestamp = DateTime.UtcNow
                };

                // Create event
                var eventGridEvent = new EventGridEvent(
                    subject: $"blobs/{name}",
                    eventType: "BlobCreated",
                    dataVersion: "1.0",
                    data: eventData);

                // Publish to Event Grid
                await _eventGridClient.SendEventAsync(eventGridEvent);
                log.LogInformation($"Successfully published event for blob: {name}");
            }
            catch (Exception ex)
            {
                log.LogError($"Error processing blob {name}: {ex.Message}");
                throw;
            }
        }
    }
}