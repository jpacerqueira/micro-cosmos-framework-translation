using System;
using System.Diagnostics;
using System.Web.Mvc;
using BankXYZ.FraudDetection.Config;
using BankXYZ.FraudDetection.Data.Repositories;
using BankXYZ.FraudDetection.Domain;
using BankXYZ.FraudDetection.Entities;
using BankXYZ.FraudDetection.Models;
using BankXYZ.FraudDetection.Services;

namespace BankXYZ.FraudDetection.Controllers
{
    /// <summary>
    /// ASP.NET MVC 3 API controller for fraud detection endpoints.
    /// All routes are prefixed with /api/v1/.
    ///
    /// Endpoints:
    ///   POST /api/v1/authorise     — real-time fraud check, returns authorisation decision
    ///   POST /api/v1/batch/run     — triggers the batch transaction monitor on-demand
    /// </summary>
    public class FraudController : Controller
    {
        private readonly IFraudRulesService        _fraudRulesService;
        private readonly IAlertWriterService       _alertWriterService;
        private readonly ITransactionMonitorService _monitorService;
        private readonly ISlaBreachLogRepository   _slaBreachLogRepo;
        private readonly FraudScoringSettings      _settings;

        public FraudController(
            IFraudRulesService         fraudRulesService,
            IAlertWriterService        alertWriterService,
            ITransactionMonitorService monitorService,
            ISlaBreachLogRepository    slaBreachLogRepo,
            FraudScoringSettings       settings)
        {
            _fraudRulesService  = fraudRulesService;
            _alertWriterService = alertWriterService;
            _monitorService     = monitorService;
            _slaBreachLogRepo   = slaBreachLogRepo;
            _settings           = settings;
        }

        // POST /api/v1/authorise
        [HttpPost]
        public JsonResult Authorise(FraudCheckRequest request)
        {
            Stopwatch stopwatch = Stopwatch.StartNew();

            FraudCommArea commArea = new FraudCommArea();
            commArea.TxnId        = request.TxnId;
            commArea.AcctNo       = request.AcctNo;
            commArea.TxnAmount    = request.TxnAmount;
            commArea.MerchantCode = request.MerchantCode;
            commArea.Channel      = ChannelHelper.FromString(request.Channel);
            commArea.TxnCountry   = request.TxnCountry;
            commArea.CardType     = request.CardType;
            commArea.CnpFlag      = request.CnpFlag;

            _fraudRulesService.Score(commArea, _settings.VelocityLimitRealtime);

            stopwatch.Stop();
            long elapsedMs = stopwatch.ElapsedMilliseconds;

            // SLA breach — per BRD-2009-FD-004, approve regardless of score
            // to prevent blocking genuine customers when the system is slow.
            if (elapsedMs > _settings.SlaLimitMs)
            {
                SlaBreachLog breach = new SlaBreachLog();
                breach.TxnId     = commArea.TxnId;
                breach.AcctNo    = commArea.AcctNo;
                breach.ElapsedMs = elapsedMs;
                breach.BreachTs  = DateTime.UtcNow;
                _slaBreachLogRepo.Save(breach);

                FraudCheckResponse slaResponse = new FraudCheckResponse();
                slaResponse.TxnId     = commArea.TxnId;
                slaResponse.FraudScore = commArea.FraudScore;
                slaResponse.Message   = "APPROVED - SLA EXCEEDED";
                slaResponse.ElapsedMs = elapsedMs;
                slaResponse.SetDecision(AuthDecision.Approve);

                return Json(slaResponse);
            }

            AuthDecision decision = MapDecision(commArea.FraudScore);

            if (decision == AuthDecision.Review || decision == AuthDecision.Decline)
                _alertWriterService.WriteAlert(commArea);

            string message;
            if (decision == AuthDecision.Approve)
                message = "TRANSACTION APPROVED";
            else if (decision == AuthDecision.Review)
                message = "TRANSACTION UNDER REVIEW";
            else
                message = "TRANSACTION DECLINED";

            FraudCheckResponse response = new FraudCheckResponse();
            response.TxnId     = commArea.TxnId;
            response.FraudScore = commArea.FraudScore;
            response.Message   = message;
            response.ElapsedMs = elapsedMs;
            response.SetDecision(decision);

            return Json(response);
        }

        // POST /api/v1/batch/run
        [HttpPost]
        public JsonResult RunBatch()
        {
            string result = _monitorService.ProcessBatch(_settings.MaxTransactions);
            return Json(new { Message = result });
        }

        /// <summary>
        /// Maps a composite fraud score to an authorisation decision.
        /// Score >= DeclineThreshold  -> Decline
        /// Score >= ScoreThreshold    -> Review
        /// Otherwise                  -> Approve
        /// </summary>
        private AuthDecision MapDecision(decimal score)
        {
            if (score >= _settings.DeclineThreshold) return AuthDecision.Decline;
            if (score >= _settings.ScoreThreshold)   return AuthDecision.Review;
            return AuthDecision.Approve;
        }
    }
}
