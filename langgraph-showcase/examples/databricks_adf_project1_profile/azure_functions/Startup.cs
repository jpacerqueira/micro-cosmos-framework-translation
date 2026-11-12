using Microsoft.Azure.Functions.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection;
using Azure.Messaging.EventGrid;
using Microsoft.Extensions.Logging;

[assembly: FunctionsStartup(typeof(BlobToEventGridFunction.Startup))]

namespace BlobToEventGridFunction
{
    public class Startup : FunctionsStartup
    {
        public override void Configure(IFunctionsHostBuilder builder)
        {
            builder.Services.AddLogging(loggingBuilder =>
            {
                loggingBuilder.AddApplicationInsights();
            });

            builder.Services.AddSingleton((serviceProvider) =>
            {
                string topicEndpoint = System.Environment.GetEnvironmentVariable("EventGridTopicEndpoint");
                string topicKey = System.Environment.GetEnvironmentVariable("EventGridTopicKey");
                return new EventGridPublisherClient(
                    new System.Uri(topicEndpoint),
                    new Azure.AzureKeyCredential(topicKey));
            });
        }
    }
} 