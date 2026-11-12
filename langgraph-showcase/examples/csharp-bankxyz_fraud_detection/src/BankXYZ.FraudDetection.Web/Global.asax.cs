using System.Data.Entity;
using System.Web;
using System.Web.Mvc;
using System.Web.Routing;
using Microsoft.Practices.Unity;
using BankXYZ.FraudDetection.App_Start;
using BankXYZ.FraudDetection.Batch;
using BankXYZ.FraudDetection.Config;
using BankXYZ.FraudDetection.Data;
using BankXYZ.FraudDetection.Services;

namespace BankXYZ.FraudDetection
{
    /// <summary>
    /// ASP.NET MVC 3 application entry point.
    ///
    /// On startup:
    ///   1. Registers MVC areas and routes.
    ///   2. Configures the Unity IoC container and sets the controller factory.
    ///   3. Disables EF schema auto-creation (DDL managed by mssql/ scripts).
    ///   4. Starts the nightly batch scheduler.
    ///
    /// On shutdown:
    ///   Disposes the batch scheduler and Unity container.
    /// </summary>
    public class MvcApplication : HttpApplication
    {
        private static IUnityContainer   _container;
        private static FraudBatchScheduler _batchScheduler;

        protected void Application_Start()
        {
            AreaRegistration.RegisterAllAreas();
            RouteConfig.RegisterRoutes(RouteTable.Routes);

            // Build Unity container and register it as the MVC controller factory
            _container = UnityConfig.RegisterComponents();
            ControllerBuilder.Current.SetControllerFactory(
                new UnityControllerFactory(_container));

            // Disable EF automatic schema creation / migration.
            // All DDL is applied by running the mssql/ SQL scripts.
            Database.SetInitializer<FraudDbContext>(null);

            // Start the nightly 02:00 batch scheduler
            ITransactionMonitorService monitorService = _container.Resolve<ITransactionMonitorService>();
            FraudScoringSettings       settings       = _container.Resolve<FraudScoringSettings>();

            _batchScheduler = new FraudBatchScheduler(monitorService, settings);
            _batchScheduler.Start();
        }

        protected void Application_End()
        {
            if (_batchScheduler != null)
            {
                _batchScheduler.Dispose();
                _batchScheduler = null;
            }

            if (_container != null)
            {
                _container.Dispose();
                _container = null;
            }
        }
    }
}
