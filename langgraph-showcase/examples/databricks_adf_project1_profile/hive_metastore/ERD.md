# Entity Relationship Diagram — project1_databricks_adf Hive Metastore

57 tables · 15 schemas · 6 domains · rendered in Mermaid (paste into https://mermaid.live) + DOT source for SVG.

---

## 1. Domain-Level Data Flow (Overview)

```mermaid
flowchart TD
    subgraph RAW["🟤 BRONZE — product_systems_raw"]
        nm_item["nm_item\n(ItemNumber PK)"]
        nm_item_supplier_raw["nm_item_supplier\n(ItemNumber,SupplierID)"]
        nm_item_detail["nm_item_detail\n(ItemNumber,OptionCode)"]
        nm_item_text["nm_item_text\n(ItemNumber,LanguageCode)"]
        nm_supplier["nm_supplier\n(SupplierID PK)"]
        nm_booking_report["nm_booking_report\n(BookingID PK)"]
        item_season_raw["item_season\n(ItemNumber,SeasonCode)"]
    end

    subgraph SILVER["🟡 SILVER — product_systems"]
        ps_nm_item_supplier["nm_item_supplier\n(conformed)"]
        ps_item_season["item_season\n(conformed · PARTITIONED)"]
        ps_nm_item_option["nm_item_option"]
        ps_item["item"]
        ps_item_text["item_text"]
    end

    subgraph TRUSTED["🟢 GOLD — trusted (star schema hub)"]
        dim_item["dim_item\n(SCD2 · ItemSurrogateKey PK)"]
        dim_item_team["dim_item_team\n(TeamCode PK)"]
        fact_sales_orders["fact_sales_orders\n(PARTITIONED BY OrderDate)"]
        fact_return_rate["fact_return_rate_item\n(ItemNumber,WeekStartDate)"]
    end

    subgraph REFINED["🔵 REFINED"]
        fso_season["fact_sales_orders_season\n(PARTITIONED BY SeasonCode)"]
        dim_item_attr["dim_item_attribute"]
    end

    subgraph BISMERGED["🔮 BISMERGED"]
        svoc["svoc_customers\n(CustomerID PK · ORPHAN)"]
    end

    subgraph BRANDED["🟣 BRANDED SPOKE — branded_prod"]
        noclick["noclick_stock_levels\n(wasb:// source)"]
        attribution["attribution_* ×15\n(CTAS write-backs)"]
    end

    subgraph GENERIC_ETL["⚙️ GENERIC ETL — bronze / silver / gold"]
        b_ct["bronze.customer_transactions"]
        s_ct["silver.customer_transactions"]
        g_ct["gold.customer_transactions__daily"]
        b_pi["bronze.product_inventory"]
        s_pi["silver.product_inventory"]
        g_pi["gold.product_inventory__summary"]
        g_fso["gold.fact_sales_orders_daily"]
        g_isp["gold.item_season_performance"]
        g_pps["gold.payment_provider_summary"]
    end

    subgraph PAYMENTS["💳 PAYMENTS — 5 diagnostic catalogs"]
        wp["wp_diagnostic\n.payment_events"]
        ap["ap_diagnostic\n.payment_events"]
        pp["pp_diagnostic\n.payment_events"]
        gp["gp_diagnostic\n.payment_events"]
        kl["klarna_diagnostic\n.payment_events"]
    end

    subgraph LOGISTICS["🚚 WAREHOUSE LOGISTICS — streaming"]
        bpp_events["bpp_parcel_events\n(Eventarc streaming)"]
        bpp_status["bpp_delivery_status\n(current snapshot)"]
    end

    %% Bronze → Silver
    nm_item --> ps_item
    nm_item --> nm_item_detail
    nm_item_supplier_raw -->|"conform"| ps_nm_item_supplier
    item_season_raw -->|"conform"| ps_item_season
    nm_supplier --> nm_item_supplier_raw

    %% Silver → Gold (trusted)
    ps_item -->|"SCD2 merge"| dim_item
    ps_nm_item_supplier -->|"join"| dim_item
    ps_item_season --> dim_item
    dim_item_team --> dim_item

    %% Star schema relationships
    fact_sales_orders -->|"ItemNumber FK"| dim_item
    fact_return_rate -->|"ItemNumber FK"| dim_item

    %% Gold → Refined
    dim_item -->|"denormalise"| fso_season
    fact_sales_orders -->|"seasonal agg"| fso_season
    ps_item_season -->|"season join"| fso_season
    dim_item --> dim_item_attr

    %% Refined → SVOC
    fact_sales_orders -->|"CustomerID"| svoc
    bpp_status -->|"logistics signal"| svoc

    %% CTAS write-back (BIS → Branded)
    fso_season ==>|"15×CTAS\nmaterialise_attribution_targets()"| attribution
    dim_item -->|"cross-catalog join\nItemNumber"| noclick

    %% Generic ETL
    b_ct -->|"process_data()"| s_ct --> g_ct
    b_pi -->|"process_data()"| s_pi --> g_pi
    fact_sales_orders -->|"BISPipeline"| g_fso
    ps_item_season -->|"BISAnalytics"| g_isp

    %% Payments
    wp --> g_pps
    ap --> g_pps
    pp --> g_pps
    gp --> g_pps
    kl --> g_pps
    fact_sales_orders -.->|"ExternalOrderRef\n↔ Payload$.order_id\ncross-catalog"| kl

    %% Logistics
    bpp_events -->|"latest status"| bpp_status
    fact_sales_orders -.->|"OrderId FK"| bpp_events

    classDef raw fill:#c8a97e,color:#000,stroke:#8a6a3e
    classDef silver fill:#f5e77a,color:#000,stroke:#c9b830
    classDef gold fill:#90c97e,color:#000,stroke:#4a8a3e
    classDef refined fill:#7eb0c9,color:#000,stroke:#3e6a8a
    classDef merged fill:#b07ec9,color:#000,stroke:#6a3e8a
    classDef branded fill:#c97eaf,color:#000,stroke:#8a3e6a
    classDef payments fill:#7ec9c5,color:#000,stroke:#3e8a87
    classDef logistics fill:#c9997e,color:#000,stroke:#8a5a3e

    class nm_item,nm_item_supplier_raw,nm_item_detail,nm_item_text,nm_supplier,nm_booking_report,item_season_raw raw
    class ps_nm_item_supplier,ps_item_season,ps_nm_item_option,ps_item,ps_item_text silver
    class dim_item,dim_item_team,fact_sales_orders,fact_return_rate gold
    class fso_season,dim_item_attr refined
    class svoc merged
    class noclick,attribution branded
    class b_ct,s_ct,g_ct,b_pi,s_pi,g_pi,g_fso,g_isp,g_pps raw
    class wp,ap,pp,gp,kl payments
    class bpp_events,bpp_status logistics
```

---

## 2. BIS Star Schema — Core Tables (detailed)

```mermaid
erDiagram

    RAW_NM_ITEM {
        string ItemNumber PK
        string ItemName
        string ProductCategory
        string SubCategory
        string BrandCode
        decimal RetailPrice
        decimal CostPrice
        string Department
        string ClassCode
        boolean IsActive
        date LaunchDate
        date EndDate
        string CountryOfOrigin
    }

    RAW_NM_SUPPLIER {
        string SupplierID PK
        string SupplierName
        string SupplierGroup
        string CountryCode
        string CurrencyCode
        int PaymentTermsDays
        string Status
        date OnboardedDate
    }

    RAW_NM_ITEM_SUPPLIER {
        string ItemNumber FK
        string SupplierID FK
        string Status
        int LeadTimeDays
        int MinOrderQty
        decimal CostPrice
        boolean IsPreferred
        date CreatedDate
    }

    RAW_NM_ITEM_DETAIL {
        string ItemNumber FK
        string OptionCode
        string BarCode
        decimal Weight
        decimal Height
        decimal Width
        string FabricContent
        boolean IsActive
    }

    RAW_NM_ITEM_TEXT {
        string ItemNumber FK
        string LanguageCode
        string Title
        string LongDescription
        string BulletPoints
    }

    RAW_ITEM_SEASON {
        string ItemNumber FK
        string SeasonCode
        date SeasonStartDate
        date SeasonEndDate
        string RangeStatus
        string TeamCode FK
        boolean IsCarryOver
    }

    RAW_NM_BOOKING_REPORT {
        string BookingID PK
        string ItemNumber FK
        string SupplierID FK
        string SeasonCode
        int BuyQuantity
        int ConfirmedQuantity
        decimal UnitCostPrice
        date DeliveryWindowStart
        date DeliveryWindowEnd
        string BookingStatus
    }

    PS_ITEM {
        string ItemNumber PK
        string ItemName
        string ProductCategory
        string SubCategory
        string BrandCode
        decimal RetailPrice
        decimal CostPrice
        boolean IsActive
        date LaunchDate
        date EndDate
    }

    PS_NM_ITEM_SUPPLIER {
        string ItemNumber FK
        string SupplierID FK
        string Status
        int LeadTimeDays
        decimal CostPrice
        boolean IsPreferred
        date CreatedDate
        timestamp _processing_timestamp
    }

    PS_ITEM_SEASON {
        string ItemNumber FK
        string SeasonCode
        date SeasonStartDate
        date SeasonEndDate
        string RangeStatus
        string TeamCode FK
        boolean IsCarryOver
    }

    PS_NM_ITEM_OPTION {
        string ItemNumber FK
        string OptionCode
        string ColourCode
        string SizeCode
        string BarCode
        boolean IsActive
    }

    TRUSTED_DIM_ITEM_TEAM {
        string TeamCode PK
        string TeamName
        string DivisionCode
        string DivisionName
        string DirectorName
        boolean IsActive
        date EffectiveDate
    }

    TRUSTED_DIM_ITEM {
        bigint ItemSurrogateKey PK
        string ItemNumber
        string ProductCategory
        string SubCategory
        string BrandCode
        string TeamCode FK
        string SupplierID FK
        decimal RetailPrice
        decimal CostPrice
        boolean IsActive
        date EffectiveDate
        date ExpiryDate
        boolean IsCurrentRecord
    }

    TRUSTED_FACT_SALES_ORDERS {
        string OrderID
        string OrderLineID
        string ItemNumber FK
        bigint ItemSurrogateKey FK
        string CustomerID
        date OrderDate
        decimal OrderAmount
        int Quantity
        string ChannelCode
        string PromoCode
        decimal DiscountAmount
        string ExternalOrderRef
        boolean ReturnFlag
        date ReturnDate
    }

    TRUSTED_FACT_RETURN_RATE_ITEM {
        string ItemNumber FK
        date WeekStartDate
        int TotalUnitsSold
        int TotalUnitsReturned
        decimal ReturnRatePct
        string ReturnReasonTop
    }

    RAW_NM_ITEM ||--o{ RAW_NM_ITEM_SUPPLIER : "has suppliers"
    RAW_NM_SUPPLIER ||--o{ RAW_NM_ITEM_SUPPLIER : "supplies items"
    RAW_NM_ITEM ||--o{ RAW_NM_ITEM_DETAIL : "has options"
    RAW_NM_ITEM ||--o{ RAW_NM_ITEM_TEXT : "has copy"
    RAW_NM_ITEM ||--o{ RAW_ITEM_SEASON : "appears in seasons"
    RAW_NM_ITEM ||--o{ RAW_NM_BOOKING_REPORT : "has bookings"
    RAW_NM_SUPPLIER ||--o{ RAW_NM_BOOKING_REPORT : "fulfils bookings"

    RAW_NM_ITEM ||--|| PS_ITEM : "conformed to"
    RAW_NM_ITEM_SUPPLIER ||--o{ PS_NM_ITEM_SUPPLIER : "conformed to"
    RAW_ITEM_SEASON ||--o{ PS_ITEM_SEASON : "conformed to"
    PS_ITEM ||--o{ PS_NM_ITEM_OPTION : "has options"

    PS_ITEM ||--|{ TRUSTED_DIM_ITEM : "SCD2 merge"
    PS_NM_ITEM_SUPPLIER }o--|| TRUSTED_DIM_ITEM : "enriches"
    TRUSTED_DIM_ITEM_TEAM ||--o{ TRUSTED_DIM_ITEM : "owns items"
    PS_ITEM_SEASON }o--o{ TRUSTED_DIM_ITEM : "cross-season"

    TRUSTED_DIM_ITEM ||--o{ TRUSTED_FACT_SALES_ORDERS : "ordered"
    TRUSTED_DIM_ITEM ||--o{ TRUSTED_FACT_RETURN_RATE_ITEM : "returned"
```

---

## 3. Refined + SVOC + Branded Write-backs

```mermaid
erDiagram

    TRUSTED_DIM_ITEM {
        bigint ItemSurrogateKey PK
        string ItemNumber
        string BrandCode
        string TeamCode FK
        boolean IsCurrentRecord
    }

    TRUSTED_FACT_SALES_ORDERS {
        string OrderID
        string ItemNumber FK
        string CustomerID
        date OrderDate
        decimal OrderAmount
        string ExternalOrderRef
    }

    PS_ITEM_SEASON {
        string ItemNumber FK
        string SeasonCode
        date SeasonStartDate
        date SeasonEndDate
        string TeamCode FK
    }

    REFINED_FACT_SALES_ORDERS_SEASON {
        string ItemNumber FK
        string SeasonCode FK
        string ProductCategory
        string BrandCode
        string TeamCode
        decimal SeasonRevenue
        int SeasonUnitsSold
        int UniqueCustomers
        decimal ReturnRatePct
        decimal PreSeasonRevenue
        int SeasonRank
        boolean IsTopPerformer
    }

    REFINED_DIM_ITEM_ATTRIBUTE {
        string ItemNumber FK
        string OptionCode FK
        string ColourCode
        string ColourFamily
        string SizeCode
        string FabricContent
        boolean IsVegan
        boolean IsSustainable
    }

    BISMERGED_SVOC_CUSTOMERS {
        string CustomerID PK
        date FirstOrderDate
        date LastOrderDate
        decimal TotalLifetimeRevenue
        int TotalLifetimeOrders
        int TotalLifetimeReturns
        string FavouriteCategory
        string FavouriteBrand
        decimal ReturnRatePct
        string LastPaymentProvider
        boolean HasOpenDispute
        boolean KlarnaCustomer
        string CustomerSegment
        boolean IsActiveCustomer
        date SnapshotDate
    }

    BRANDED_NOCLICK_STOCK_LEVELS {
        string ItemNumber FK
        string WarehouseLocation
        int StockLevel
        int ReservedUnits
        int AvailableUnits
        string StockStatus
        date LastCountDate
    }

    BRANDED_ATTRIBUTION_ITEM_SEASON {
        string ItemNumber FK
        string SeasonCode
        string ProductCategory
        string BrandCode
        decimal SeasonRevenue
        int UniqueCustomers
        date PreSeasonCutoff
        timestamp _generated_at
    }

    BRANDED_ATTRIBUTION_RETURN_RATE {
        string ItemNumber FK
        string SeasonCode
        decimal ReturnRatePct
        string TopReturnReason
        decimal ReturnCostGbp
        timestamp _generated_at
    }

    BRANDED_ATTRIBUTION_STOCK_COVER {
        string ItemNumber FK
        string SeasonCode
        decimal AvgStockLevel
        decimal StockCoverWeeks
        int OutOfStockDays
        timestamp _generated_at
    }

    BRANDED_ATTRIBUTION_FORECAST_ACCURACY {
        string ItemNumber FK
        string SeasonCode
        int ForecastedUnits
        int ActualUnitsSold
        decimal ForecastAccuracyPct
        int ForecastBias
        timestamp _generated_at
    }

    BRANDED_ATTRIBUTION_15_OTHERS {
        string ItemNumber FK
        string SeasonCode
        string metric_columns "..."
        timestamp _generated_at
    }

    TRUSTED_FACT_SALES_ORDERS ||--o{ REFINED_FACT_SALES_ORDERS_SEASON : "seasonal aggregation"
    PS_ITEM_SEASON ||--o{ REFINED_FACT_SALES_ORDERS_SEASON : "season filter"
    TRUSTED_DIM_ITEM ||--o{ REFINED_FACT_SALES_ORDERS_SEASON : "denormalise"
    TRUSTED_DIM_ITEM ||--o{ REFINED_DIM_ITEM_ATTRIBUTE : "item attributes"

    TRUSTED_FACT_SALES_ORDERS }o--|| BISMERGED_SVOC_CUSTOMERS : "lifetime signals"
    TRUSTED_DIM_ITEM ||--o{ BRANDED_NOCLICK_STOCK_LEVELS : "cross-catalog join"

    REFINED_FACT_SALES_ORDERS_SEASON ||--|| BRANDED_ATTRIBUTION_ITEM_SEASON : "CTAS write-back 1"
    BRANDED_NOCLICK_STOCK_LEVELS ||--o{ REFINED_FACT_SALES_ORDERS_SEASON : "stock cover input"
    REFINED_FACT_SALES_ORDERS_SEASON ||--|| BRANDED_ATTRIBUTION_RETURN_RATE : "CTAS write-back 6"
    REFINED_FACT_SALES_ORDERS_SEASON ||--|| BRANDED_ATTRIBUTION_STOCK_COVER : "CTAS write-back 7"
    REFINED_FACT_SALES_ORDERS_SEASON ||--|| BRANDED_ATTRIBUTION_FORECAST_ACCURACY : "CTAS write-back 8"
    REFINED_FACT_SALES_ORDERS_SEASON ||--|| BRANDED_ATTRIBUTION_15_OTHERS : "CTAS write-backs 2-5,9-15"
```

---

## 4. Payment Diagnostics — 5 Providers

```mermaid
erDiagram

    WP_PAYMENT_EVENTS {
        string EventId PK
        string EventType
        timestamp EventTimestamp
        string Payload "JSON: $.transaction_id $.amount $.currency $.status $.customer_email $.error_code"
        string GatewayReference
        string SiteId
        date EventDate
    }

    AP_PAYMENT_EVENTS {
        string EventId PK
        string EventType
        timestamp EventTimestamp
        string Payload "JSON: $.order_reference_id $.dispute_id $.amount.value $.amount.currencyCode $.reason_code"
        string MerchantId
        string MarketplaceId
        date EventDate
    }

    PP_PAYMENT_EVENTS {
        string EventId PK
        string EventType
        timestamp EventTimestamp
        string Payload "JSON: $.id $.status $.amount.value $.payer.email $.failure_reason"
        string PayPalAccountId
        date EventDate
    }

    GP_PAYMENT_EVENTS {
        string EventId PK
        string EventType
        timestamp EventTimestamp
        string Payload "JSON: $.result_code $.decline_reason"
        string MerchantId
        date EventDate
    }

    KLARNA_PAYMENT_EVENTS {
        string EventId PK
        string EventType
        timestamp EventTimestamp
        string Payload "JSON: $.order_id $.capture_amount $.settlement_date $.event_type"
        string KlarnaOrderId "promoted from Payload for index join"
        string MerchantReference
        date EventDate
    }

    TRUSTED_FACT_SALES_ORDERS {
        string OrderID
        string ExternalOrderRef "cross-catalog join key"
        date OrderDate
        decimal OrderAmount
    }

    GOLD_PAYMENT_PROVIDER_SUMMARY {
        string Provider PK
        bigint EventCount
        decimal TotalAmount
        timestamp _serving_timestamp
    }

    KLARNA_PAYMENT_EVENTS }o--o| TRUSTED_FACT_SALES_ORDERS : "KlarnaOrderId = ExternalOrderRef (cross-catalog reconciliation)"

    WP_PAYMENT_EVENTS ||--o{ GOLD_PAYMENT_PROVIDER_SUMMARY : "UNION ALL aggregate"
    AP_PAYMENT_EVENTS ||--o{ GOLD_PAYMENT_PROVIDER_SUMMARY : "UNION ALL aggregate"
    PP_PAYMENT_EVENTS ||--o{ GOLD_PAYMENT_PROVIDER_SUMMARY : "UNION ALL aggregate"
    GP_PAYMENT_EVENTS ||--o{ GOLD_PAYMENT_PROVIDER_SUMMARY : "UNION ALL aggregate"
    KLARNA_PAYMENT_EVENTS ||--o{ GOLD_PAYMENT_PROVIDER_SUMMARY : "UNION ALL aggregate"
```

---

## 5. Generic ETL Pipeline (etl_config.json)

```mermaid
erDiagram

    BRONZE_CUSTOMER_TRANSACTIONS {
        string transaction_id
        string customer_id
        string amount "raw STRING"
        string transaction_date "raw STRING"
        string transaction_type
        string channel
        string product_id
        string status
    }

    SILVER_CUSTOMER_TRANSACTIONS {
        string transaction_id PK
        string customer_id
        decimal amount "DECIMAL(10,2)"
        timestamp transaction_date "TIMESTAMP cast"
        string transaction_type
        string channel
        string product_id
        string status
    }

    GOLD_CUSTOMER_TRANSACTIONS_DAILY {
        string customer_id
        timestamp transaction_date
        decimal total_amount
        bigint transaction_count
        decimal avg_amount
    }

    BRONZE_PRODUCT_INVENTORY {
        string product_id
        string price "raw STRING"
        string quantity "raw STRING"
        string last_updated "raw STRING"
        string product_category
        string supplier_id
    }

    SILVER_PRODUCT_INVENTORY {
        string product_id PK
        decimal price "DECIMAL(10,2)"
        int quantity "INT cast"
        timestamp last_updated "TIMESTAMP cast"
        string product_category
        string supplier_id
    }

    GOLD_PRODUCT_INVENTORY_SUMMARY {
        string product_category PK
        bigint total_quantity
        decimal total_value
        bigint product_count
    }

    SILVER_NM_ITEM_SUPPLIER {
        string item_number FK
        string supplier_id FK
        int lead_time_days
        decimal cost_price
        string status
        timestamp created_date
    }

    SILVER_ITEM_SEASON {
        string item_number FK
        string season_code
        timestamp season_start_date
        timestamp season_end_date
    }

    SILVER_FACT_SALES_ORDERS {
        string order_id
        string item_number FK
        string customer_id
        timestamp order_date
        decimal order_amount
        int quantity
    }

    SILVER_DIM_ITEM {
        string item_number PK
        string product_category
        string brand_code
        decimal retail_price
        timestamp effective_date
        timestamp expiry_date
    }

    GOLD_FACT_SALES_ORDERS_DAILY {
        string item_number FK
        date order_date
        string product_category
        string brand_code
        decimal total_revenue
        bigint order_count
    }

    GOLD_ITEM_SEASON_PERFORMANCE {
        string item_number FK
        string season_code FK
        string product_category
        decimal total_revenue
        bigint order_count
        decimal avg_order_value
    }

    BRONZE_CUSTOMER_TRANSACTIONS ||--|| SILVER_CUSTOMER_TRANSACTIONS : "ETLPipeline.process_data()"
    SILVER_CUSTOMER_TRANSACTIONS ||--|| GOLD_CUSTOMER_TRANSACTIONS_DAILY : "ETLPipeline.serve_data()"

    BRONZE_PRODUCT_INVENTORY ||--|| SILVER_PRODUCT_INVENTORY : "ETLPipeline.process_data()"
    SILVER_PRODUCT_INVENTORY ||--|| GOLD_PRODUCT_INVENTORY_SUMMARY : "ETLPipeline.serve_data()"

    SILVER_FACT_SALES_ORDERS ||--o{ GOLD_FACT_SALES_ORDERS_DAILY : "BISPipeline.serve_fact_sales_orders()"
    SILVER_DIM_ITEM ||--o{ GOLD_FACT_SALES_ORDERS_DAILY : "join for category/brand"
    SILVER_ITEM_SEASON ||--o{ GOLD_ITEM_SEASON_PERFORMANCE : "BISAnalytics notebook"
    SILVER_DIM_ITEM ||--o{ GOLD_ITEM_SEASON_PERFORMANCE : "join for attributes"
    SILVER_NM_ITEM_SUPPLIER }o--|| SILVER_DIM_ITEM : "supplier enrichment"
```

---

## 6. Warehouse Logistics — Streaming Domain

```mermaid
erDiagram

    BPP_PARCEL_EVENTS {
        string EventId PK
        string ParcelId
        string OrderId FK
        string EventType "DESPATCHED|IN_TRANSIT|OUT_FOR_DELIVERY|DELIVERED|RETURNED|FAILED|EXCEPTION"
        timestamp EventTimestamp
        string CarrierCode
        string TrackingNumber
        string WarehouseId
        string DestinationPostcode
        int DeliveryAttempt
        string FailureReason
        date EstimatedDelivery
        timestamp ActualDelivery
        boolean IsLateDelivery
    }

    BPP_DELIVERY_STATUS {
        string ParcelId PK
        string OrderId FK
        string LatestStatus
        timestamp LatestEventTime
        string CarrierCode
        int DeliveryAttempts
        boolean IsDelivered
        boolean IsReturned
        date EstimatedDelivery
        timestamp ActualDelivery
        boolean IsLate
    }

    TRUSTED_FACT_SALES_ORDERS {
        string OrderID PK
        string CustomerID
        date OrderDate
        decimal OrderAmount
    }

    BISMERGED_SVOC_CUSTOMERS {
        string CustomerID PK
        date LastDeliveryDate "from BPP Phase3+"
        decimal DeliverySuccessRate "from BPP Phase3+"
        string CustomerSegment
    }

    BPP_PARCEL_EVENTS }o--|| TRUSTED_FACT_SALES_ORDERS : "OrderId FK (Phase 3+)"
    BPP_PARCEL_EVENTS ||--|{ BPP_DELIVERY_STATUS : "latest event per parcel"
    BPP_DELIVERY_STATUS }o--o| BISMERGED_SVOC_CUSTOMERS : "logistics signal (Phase 3+)"
```

---

## 7. Cross-Catalog Relationship Map

```mermaid
flowchart LR
    subgraph BIS["businessintelligencesystems_prod"]
        di["trusted.dim_item\n(ItemNumber)"]
        fso["trusted.fact_sales_orders\n(ExternalOrderRef)"]
    end

    subgraph BRANDED["branded_prod"]
        noclick["noclick_stock_levels\n(ItemNumber)"]
        attr["attribution_* ×15\n(ItemNumber, SeasonCode)"]
    end

    subgraph PAYMENTS["payment diagnostics"]
        kl["klarna_diagnostic\n.payment_events\n(KlarnaOrderId)"]
    end

    subgraph LOGISTICS["warehouselogistics_prod"]
        bpp["bpp_parcel_events\n(OrderId)"]
    end

    di -.->|"ItemNumber\ncross-catalog join"| noclick
    di ==>|"CTAS write-back\n×15 targets"| attr
    fso -.->|"ExternalOrderRef\n= Payload$.order_id"| kl
    fso -.->|"OrderID\nPhase 3+"| bpp

    style BIS fill:#e8f5e9,stroke:#4caf50
    style BRANDED fill:#fce4ec,stroke:#e91e63
    style PAYMENTS fill:#e3f2fd,stroke:#2196f3
    style LOGISTICS fill:#fff3e0,stroke:#ff9800
```

---

## 8. DBML — for dbdiagram.io interactive viewer

Paste the block below at https://dbdiagram.io to render an interactive ERD.

```dbml
// =====================================================================
// project1_databricks_adf — Hive Metastore DBML
// Paste at https://dbdiagram.io
// =====================================================================

Table product_systems_raw.nm_item {
  ItemNumber         varchar [pk, note: "ERP item identifier"]
  ItemName           varchar
  ProductCategory    varchar
  SubCategory        varchar
  BrandCode          varchar
  RetailPrice        decimal
  CostPrice          decimal
  Department         varchar
  ClassCode          varchar
  IsActive           boolean
  LaunchDate         date
  EndDate            date
  CountryOfOrigin    varchar
  _ingestion_timestamp timestamp
}

Table product_systems_raw.nm_supplier {
  SupplierID        varchar [pk]
  SupplierName      varchar
  SupplierGroup     varchar
  CountryCode       varchar
  CurrencyCode      varchar
  PaymentTermsDays  int
  Status            varchar
  OnboardedDate     date
}

Table product_systems_raw.nm_item_supplier {
  ItemNumber    varchar [ref: > product_systems_raw.nm_item.ItemNumber]
  SupplierID    varchar [ref: > product_systems_raw.nm_supplier.SupplierID]
  Status        varchar
  LeadTimeDays  int
  CostPrice     decimal
  IsPreferred   boolean
  CreatedDate   date

  indexes {
    (ItemNumber, SupplierID) [pk]
  }
}

Table product_systems_raw.nm_item_detail {
  ItemNumber  varchar [ref: > product_systems_raw.nm_item.ItemNumber]
  OptionCode  varchar
  BarCode     varchar
  Weight      decimal
  FabricContent varchar
  IsActive    boolean

  indexes {
    (ItemNumber, OptionCode) [pk]
  }
}

Table product_systems_raw.nm_item_text {
  ItemNumber    varchar [ref: > product_systems_raw.nm_item.ItemNumber]
  LanguageCode  varchar
  Title         varchar
  LongDescription varchar
  BulletPoints  varchar

  indexes {
    (ItemNumber, LanguageCode) [pk]
  }
}

Table product_systems_raw.item_season {
  ItemNumber      varchar [ref: > product_systems_raw.nm_item.ItemNumber]
  SeasonCode      varchar
  SeasonStartDate date
  SeasonEndDate   date
  RangeStatus     varchar
  TeamCode        varchar
  IsCarryOver     boolean

  indexes {
    (ItemNumber, SeasonCode) [pk]
  }
}

Table product_systems_raw.nm_booking_report {
  BookingID          varchar [pk]
  ItemNumber         varchar [ref: > product_systems_raw.nm_item.ItemNumber]
  SupplierID         varchar [ref: > product_systems_raw.nm_supplier.SupplierID]
  SeasonCode         varchar
  BuyQuantity        int
  ConfirmedQuantity  int
  UnitCostPrice      decimal
  DeliveryWindowStart date
  DeliveryWindowEnd   date
  BookingStatus       varchar
}

Table product_systems.item {
  ItemNumber      varchar [pk]
  ItemName        varchar
  ProductCategory varchar
  BrandCode       varchar
  RetailPrice     decimal
  IsActive        boolean
  LaunchDate      date
}

Table product_systems.nm_item_supplier {
  ItemNumber    varchar [ref: > product_systems.item.ItemNumber]
  SupplierID    varchar
  Status        varchar
  LeadTimeDays  int
  CostPrice     decimal
  IsPreferred   boolean
  CreatedDate   date
  _processing_timestamp timestamp

  indexes {
    (ItemNumber, SupplierID) [pk]
  }
}

Table product_systems.item_season {
  ItemNumber      varchar [ref: > product_systems.item.ItemNumber]
  SeasonCode      varchar
  SeasonStartDate date
  SeasonEndDate   date
  RangeStatus     varchar
  TeamCode        varchar
  IsCarryOver     boolean

  indexes {
    (ItemNumber, SeasonCode) [pk]
  }
}

Table product_systems.nm_item_option {
  ItemNumber   varchar [ref: > product_systems.item.ItemNumber]
  OptionCode   varchar
  ColourCode   varchar
  SizeCode     varchar
  BarCode      varchar
  IsActive     boolean

  indexes {
    (ItemNumber, OptionCode) [pk]
  }
}

Table trusted.dim_item_team {
  TeamCode      varchar [pk]
  TeamName      varchar
  DivisionCode  varchar
  DivisionName  varchar
  IsActive      boolean
}

Table trusted.dim_item {
  ItemSurrogateKey bigint [pk, increment]
  ItemNumber       varchar [note: "natural key; join on IsCurrentRecord=TRUE"]
  ProductCategory  varchar
  BrandCode        varchar
  TeamCode         varchar [ref: > trusted.dim_item_team.TeamCode]
  SupplierID       varchar
  RetailPrice      decimal
  IsCurrentRecord  boolean
  EffectiveDate    date
  ExpiryDate       date
}

Table trusted.fact_sales_orders {
  OrderID           varchar
  OrderLineID       varchar
  ItemNumber        varchar [ref: > trusted.dim_item.ItemNumber]
  ItemSurrogateKey  bigint  [ref: > trusted.dim_item.ItemSurrogateKey]
  CustomerID        varchar
  OrderDate         date
  OrderAmount       decimal
  ChannelCode       varchar
  ExternalOrderRef  varchar [note: "cross-catalog join key to klarna_diagnostic"]
  ReturnFlag        boolean
  ReturnDate        date

  indexes {
    (OrderID, ItemNumber) [pk]
    OrderDate
  }
}

Table trusted.fact_return_rate_item {
  ItemNumber       varchar [ref: > trusted.dim_item.ItemNumber]
  WeekStartDate    date
  TotalUnitsSold   int
  TotalUnitsReturned int
  ReturnRatePct    decimal
  ReturnReasonTop  varchar

  indexes {
    (ItemNumber, WeekStartDate) [pk]
  }
}

Table refined.fact_sales_orders_season {
  ItemNumber       varchar [ref: > trusted.dim_item.ItemNumber]
  SeasonCode       varchar [ref: > product_systems.item_season.SeasonCode]
  ProductCategory  varchar
  BrandCode        varchar
  TeamCode         varchar
  SeasonRevenue    decimal
  SeasonUnitsSold  int
  UniqueCustomers  int
  ReturnRatePct    decimal
  SeasonRank       int
  IsTopPerformer   boolean

  indexes {
    (ItemNumber, SeasonCode) [pk]
  }
}

Table refined.dim_item_attribute {
  ItemNumber    varchar [ref: > trusted.dim_item.ItemNumber]
  OptionCode    varchar
  ColourCode    varchar
  ColourFamily  varchar
  SizeCode      varchar
  IsVegan       boolean
  IsSustainable boolean

  indexes {
    (ItemNumber, OptionCode) [pk]
  }
}

Table bismerged.svoc_customers {
  CustomerID             varchar [pk]
  FirstOrderDate         date
  LastOrderDate          date
  TotalLifetimeRevenue   decimal
  TotalLifetimeOrders    int
  FavouriteCategory      varchar
  LastPaymentProvider    varchar
  HasOpenDispute         boolean
  KlarnaCustomer         boolean
  LastDeliveryDate       date
  CustomerSegment        varchar
  SnapshotDate           date
}

Table branded_prod.noclick_stock_levels {
  ItemNumber        varchar [ref: > trusted.dim_item.ItemNumber, note: "cross-catalog join"]
  WarehouseLocation varchar
  StockLevel        int
  AvailableUnits    int
  StockStatus       varchar
  LastCountDate     date
}

Table branded_prod.attribution_item_season {
  ItemNumber      varchar [ref: > refined.fact_sales_orders_season.ItemNumber]
  SeasonCode      varchar [ref: > refined.fact_sales_orders_season.SeasonCode]
  SeasonRevenue   decimal
  UniqueCustomers int
  PreSeasonCutoff date
  _generated_at   timestamp

  indexes {
    (ItemNumber, SeasonCode) [pk]
  }
}

// Attribution tables 2-15 follow same structure (ItemNumber, SeasonCode PK + metric columns)
// See 05_branded_prod.sql for full definitions of:
//   attribution_item_team, attribution_item_brand, attribution_sales_weekly,
//   attribution_sales_monthly, attribution_return_rate, attribution_stock_cover,
//   attribution_forecast_accuracy, attribution_supplier_lead_time,
//   attribution_noclick_opportunity, attribution_svoc_segment,
//   attribution_price_elasticity, attribution_channel_mix,
//   attribution_markdown_impact, attribution_new_season_launch

Table wp_diagnostic.payment_events {
  EventId          varchar [pk]
  EventType        varchar
  EventTimestamp   timestamp
  Payload          varchar [note: "JSON: $.transaction_id $.amount $.currency $.status $.customer_email $.error_code"]
  GatewayReference varchar
  EventDate        date
}

Table ap_diagnostic.payment_events {
  EventId        varchar [pk]
  EventType      varchar
  EventTimestamp timestamp
  Payload        varchar [note: "JSON: $.order_reference_id $.dispute_id $.amount.value $.amount.currencyCode"]
  MerchantId     varchar
  EventDate      date
}

Table pp_diagnostic.payment_events {
  EventId        varchar [pk]
  EventType      varchar
  EventTimestamp timestamp
  Payload        varchar [note: "JSON: $.id $.status $.amount.value $.payer.email $.failure_reason"]
  EventDate      date
}

Table gp_diagnostic.payment_events {
  EventId        varchar [pk]
  EventType      varchar
  EventTimestamp timestamp
  Payload        varchar [note: "JSON: $.result_code $.decline_reason"]
  MerchantId     varchar
  EventDate      date
}

Table klarna_diagnostic.payment_events {
  EventId           varchar [pk]
  EventType         varchar
  EventTimestamp    timestamp
  Payload           varchar [note: "JSON: $.order_id $.capture_amount $.settlement_date"]
  KlarnaOrderId     varchar [note: "promoted from Payload for indexed join"]
  MerchantReference varchar
  EventDate         date
}

Table warehouselogistics_prod.bpp_parcel_events {
  EventId           varchar [pk]
  ParcelId          varchar
  OrderId           varchar [ref: > trusted.fact_sales_orders.OrderID]
  EventType         varchar
  EventTimestamp    timestamp
  CarrierCode       varchar
  TrackingNumber    varchar
  DeliveryAttempt   int
  FailureReason     varchar
  EstimatedDelivery date
  ActualDelivery    timestamp
  IsLateDelivery    boolean
}

Table warehouselogistics_prod.bpp_delivery_status {
  ParcelId        varchar [pk]
  OrderId         varchar [ref: > trusted.fact_sales_orders.OrderID]
  LatestStatus    varchar
  CarrierCode     varchar
  DeliveryAttempts int
  IsDelivered     boolean
  IsReturned      boolean
  IsLate          boolean
}

// Cross-catalog relationship (cross-domain)
Ref: klarna_diagnostic.payment_events.KlarnaOrderId > trusted.fact_sales_orders.ExternalOrderRef

Table bronze.customer_transactions {
  transaction_id   varchar
  customer_id      varchar
  amount           varchar [note: "raw STRING"]
  transaction_date varchar [note: "raw STRING"]
  transaction_type varchar
  channel          varchar
}

Table silver.customer_transactions {
  transaction_id   varchar [pk]
  customer_id      varchar
  amount           decimal [note: "DECIMAL(10,2)"]
  transaction_date timestamp
  transaction_type varchar
  channel          varchar
}

Table gold.customer_transactions__daily_transactions {
  customer_id       varchar
  transaction_date  timestamp
  total_amount      decimal
  transaction_count bigint
  avg_amount        decimal

  indexes {
    (customer_id, transaction_date) [pk]
  }
}

Table bronze.product_inventory {
  product_id       varchar
  price            varchar [note: "raw STRING"]
  quantity         varchar [note: "raw STRING"]
  product_category varchar
  supplier_id      varchar
}

Table silver.product_inventory {
  product_id       varchar [pk]
  price            decimal [note: "DECIMAL(10,2)"]
  quantity         int
  product_category varchar
  supplier_id      varchar
}

Table gold.product_inventory__inventory_summary {
  product_category varchar [pk]
  total_quantity   bigint
  total_value      decimal
  product_count    bigint
}

Ref: bronze.customer_transactions.transaction_id > silver.customer_transactions.transaction_id
Ref: silver.customer_transactions.customer_id > gold.customer_transactions__daily_transactions.customer_id
Ref: bronze.product_inventory.product_id > silver.product_inventory.product_id
Ref: silver.product_inventory.product_category > gold.product_inventory__inventory_summary.product_category
```
