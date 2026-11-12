using System.Web.Mvc;
using System.Web.Routing;

namespace BankXYZ.FraudDetection.App_Start
{
    /// <summary>
    /// Registers MVC route table entries.
    /// All fraud API endpoints are prefixed with /api/v1/.
    /// </summary>
    public static class RouteConfig
    {
        public static void RegisterRoutes(RouteCollection routes)
        {
            routes.IgnoreRoute("{resource}.axd/{*pathInfo}");

            // POST /api/v1/batch/run — must be registered before the general /api/v1/{action} route
            routes.MapRoute(
                name:    "BatchRun",
                url:     "api/v1/batch/run",
                defaults: new { controller = "Fraud", action = "RunBatch" }
            );

            // POST /api/v1/authorise
            routes.MapRoute(
                name:    "FraudApi",
                url:     "api/v1/{action}",
                defaults: new { controller = "Fraud" }
            );
        }
    }
}
