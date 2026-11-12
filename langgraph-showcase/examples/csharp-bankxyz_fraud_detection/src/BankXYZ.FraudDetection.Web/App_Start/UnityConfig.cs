using System.Web.Mvc;
using Microsoft.Practices.Unity;
using BankXYZ.FraudDetection.Config;
using BankXYZ.FraudDetection.Data;
using BankXYZ.FraudDetection.Data.Repositories;
using BankXYZ.FraudDetection.Services;

namespace BankXYZ.FraudDetection.App_Start
{
    /// <summary>
    /// Configures the Unity 2.1 IoC container.
    ///
    /// Lifetime conventions:
    ///   - FraudScoringSettings   : ContainerControlledLifetimeManager (singleton — config read once)
    ///   - FraudDbContext         : HierarchicalLifetimeManager (one per HTTP request child container)
    ///   - Repositories           : TransientLifetimeManager (default — resolved with each dependent)
    ///   - Services               : TransientLifetimeManager (default)
    /// </summary>
    public static class UnityConfig
    {
        public static IUnityContainer RegisterComponents()
        {
            IUnityContainer container = new UnityContainer();

            // Configuration singleton — read once from web.config on startup
            FraudScoringSettings settings = FraudScoringSettings.FromConfiguration();
            container.RegisterInstance<FraudScoringSettings>(settings);

            // DbContext — one per web request (HierarchicalLifetimeManager with child container per request)
            container.RegisterType<FraudDbContext>(new HierarchicalLifetimeManager());

            // Repositories
            container.RegisterType<IAccountRepository,        AccountRepository>();
            container.RegisterType<ITransactionRepository,    TransactionRepository>();
            container.RegisterType<IMerchantRiskRepository,   MerchantRiskRepository>();
            container.RegisterType<IFraudAlertRepository,     FraudAlertRepository>();
            container.RegisterType<ICustomerProfileRepository, CustomerProfileRepository>();
            container.RegisterType<IWatchlistRepository,      WatchlistRepository>();
            container.RegisterType<IWatchlistHitRepository,   WatchlistHitRepository>();
            container.RegisterType<IMqFailureLogRepository,   MqFailureLogRepository>();
            container.RegisterType<ISlaBreachLogRepository,   SlaBreachLogRepository>();

            // Services
            container.RegisterType<IVelocityCheckService,      VelocityCheckService>();
            container.RegisterType<ICustomerProfileService,    CustomerProfileService>();
            container.RegisterType<IWatchlistService,          WatchlistService>();
            container.RegisterType<IMqNotificationService,     MqNotificationService>();
            container.RegisterType<IAlertWriterService,        AlertWriterService>();
            container.RegisterType<IFraudRulesService,         FraudRulesService>();
            container.RegisterType<ITransactionMonitorService, TransactionMonitorService>();

            return container;
        }
    }

    /// <summary>
    /// ASP.NET MVC 3 controller factory backed by Unity.
    /// Creates a child container per request so HierarchicalLifetimeManager scopes work correctly.
    /// </summary>
    public class UnityControllerFactory : DefaultControllerFactory
    {
        private readonly IUnityContainer _container;

        public UnityControllerFactory(IUnityContainer container)
        {
            _container = container;
        }

        protected override IController GetControllerInstance(
            System.Web.Routing.RequestContext requestContext,
            System.Type controllerType)
        {
            if (controllerType == null)
                return base.GetControllerInstance(requestContext, controllerType);

            // Create a child container per request for correct lifetime scoping.
            IUnityContainer childContainer = _container.CreateChildContainer();
            return (IController)childContainer.Resolve(controllerType);
        }
    }
}
