package com.bankxyz.fraud.support;

import com.bankxyz.fraud.entity.Account;
import com.bankxyz.fraud.entity.CustomerProfile;
import com.bankxyz.fraud.entity.MerchantRisk;
import com.bankxyz.fraud.entity.Transaction;
import com.bankxyz.fraud.entity.WatchlistEntry;
import com.bankxyz.fraud.repository.AccountRepository;
import com.bankxyz.fraud.repository.CustomerProfileRepository;
import com.bankxyz.fraud.repository.MerchantRiskRepository;
import com.bankxyz.fraud.repository.TransactionRepository;
import com.bankxyz.fraud.repository.WatchlistRepository;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * Test-data builders shared across step definition classes.
 * Every scenario is expected to seed only the fixtures it actually needs —
 * defaults are intentionally "no signal" (unknown merchant, no profile, no
 * watchlist hit) so composite score assertions stay hand-calculable.
 */
@Component
public class Fixtures {

    private final AccountRepository accountRepo;
    private final MerchantRiskRepository merchantRepo;
    private final CustomerProfileRepository profileRepo;
    private final WatchlistRepository watchlistRepo;
    private final TransactionRepository txnRepo;

    public Fixtures(AccountRepository accountRepo,
                     MerchantRiskRepository merchantRepo,
                     CustomerProfileRepository profileRepo,
                     WatchlistRepository watchlistRepo,
                     TransactionRepository txnRepo) {
        this.accountRepo = accountRepo;
        this.merchantRepo = merchantRepo;
        this.profileRepo = profileRepo;
        this.watchlistRepo = watchlistRepo;
        this.txnRepo = txnRepo;
    }

    public Account account(String acctNo, String custFullName, String homeCountry, String statusCode) {
        Account account = new Account();
        account.setAcctNo(acctNo);
        account.setCustId("CUST0001");
        account.setCustFullName(custFullName);
        account.setAcctStatus(statusCode);
        account.setAcctType("CU");
        account.setHomeCountry(homeCountry);
        return accountRepo.save(account);
    }

    public MerchantRisk merchant(String code, String riskBand, boolean blocked) {
        MerchantRisk merchant = new MerchantRisk();
        merchant.setMerchantCode(code);
        merchant.setMerchantName("Merchant " + code);
        merchant.setBlockedFlag(blocked ? "Y" : "N");
        merchant.setRiskBand(riskBand);
        return merchantRepo.save(merchant);
    }

    public CustomerProfile profile(String acctNo, BigDecimal avgTxnAmount, BigDecimal maxTxnAmount,
                                    String usualCountry, int usualHrStart, int usualHrEnd) {
        CustomerProfile profile = new CustomerProfile();
        profile.setAcctNo(acctNo);
        profile.setAvgTxnAmount(avgTxnAmount);
        profile.setMaxTxnAmount(maxTxnAmount);
        profile.setUsualCountry(usualCountry);
        profile.setUsualChannel("ONLINE  ");
        profile.setUsualHrStart(usualHrStart);
        profile.setUsualHrEnd(usualHrEnd);
        return profileRepo.save(profile);
    }

    public WatchlistEntry watchlistEntry(String listType, String matchName, String matchAcct) {
        WatchlistEntry entry = new WatchlistEntry();
        entry.setListType(listType);
        entry.setMatchName(matchName);
        entry.setMatchAcct(matchAcct);
        entry.setListStatus("ACTIVE");
        return watchlistRepo.save(entry);
    }

    public Transaction transaction(String txnId, String acctNo, BigDecimal amount,
                                    String channel, String txnStatus, LocalDateTime txnTs) {
        Transaction txn = new Transaction();
        txn.setTxnId(txnId);
        txn.setAcctNo(acctNo);
        txn.setTxnAmount(amount);
        txn.setChannel(channel);
        txn.setTxnCountry("GBR");
        txn.setCnpFlag("N");
        txn.setTxnStatus(txnStatus);
        txn.setTxnTs(txnTs);
        return txnRepo.save(txn);
    }
}
