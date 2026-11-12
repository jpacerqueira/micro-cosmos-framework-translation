using System;
using System.Threading;
using BankXYZ.FraudDetection.Config;
using BankXYZ.FraudDetection.Services;

namespace BankXYZ.FraudDetection.Batch
{
    /// <summary>
    /// Schedules the nightly batch fraud scan at 02:00 local time.
    /// Equivalent of a Spring @Scheduled(cron="0 0 2 * * ?") bean.
    ///
    /// Uses System.Threading.Timer (available in .NET 4.0).
    /// The timer fires once at the next 02:00, then every 24 hours thereafter.
    ///
    /// Start() must be called during application startup (Global.asax.Application_Start).
    /// Dispose() must be called during application shutdown (Global.asax.Application_End).
    /// </summary>
    public class FraudBatchScheduler : IDisposable
    {
        private Timer _timer;
        private readonly ITransactionMonitorService _monitorService;
        private readonly FraudScoringSettings       _settings;
        private bool _disposed;

        public FraudBatchScheduler(
            ITransactionMonitorService monitorService,
            FraudScoringSettings       settings)
        {
            _monitorService = monitorService;
            _settings       = settings;
        }

        /// <summary>
        /// Starts the timer. First fire is at the next 02:00 local time.
        /// Subsequent fires are at 24-hour intervals.
        /// </summary>
        public void Start()
        {
            TimeSpan timeToFirstRun = CalculateTimeUntil2Am();
            _timer = new Timer(RunBatch, null, timeToFirstRun, TimeSpan.FromDays(1));
        }

        /// <summary>
        /// Calculates the time remaining until the next 02:00 local time.
        /// If 02:00 has already passed today, the delay is to 02:00 tomorrow.
        /// </summary>
        private static TimeSpan CalculateTimeUntil2Am()
        {
            DateTime now      = DateTime.Now;
            DateTime next2Am  = now.Date.AddHours(2);

            if (next2Am <= now)
                next2Am = next2Am.AddDays(1);

            return next2Am - now;
        }

        /// <summary>
        /// Timer callback — runs the batch and discards the result string
        /// (result is visible in application logs via IIS output).
        /// </summary>
        private void RunBatch(object state)
        {
            try
            {
                _monitorService.ProcessBatch(_settings.MaxTransactions);
            }
            catch (Exception)
            {
                // Batch failures must not crash the timer thread.
                // In a production system these would be written to an error log.
            }
        }

        public void Dispose()
        {
            if (!_disposed)
            {
                if (_timer != null)
                {
                    _timer.Dispose();
                    _timer = null;
                }
                _disposed = true;
            }
        }
    }
}
