import { gql } from '@apollo/client'

export const GET_PORTFOLIOS = gql`
  query GetPortfolios($status: String) {
    portfolios(status: $status) {
      portfolioId
      name
      description
      status
      projectPhase
      cutOffDate
      finalBidDate
    }
  }
`

export const GET_PORTFOLIO = gql`
  query GetPortfolio($id: UUID!) {
    portfolio(id: $id) {
      portfolioId
      name
      description
      status
      projectPhase
      cutOffDate
      finalBidDate
      properties {
        propertyId
        name
        addressLine1
        city
        postcode
        valuation
        allocationStatus
      }
    }
  }
`

export const CREATE_PORTFOLIO = gql`
  mutation CreatePortfolio($input: CreatePortfolioInput!) {
    createPortfolio(input: $input)
  }
`

export const CLOSE_PORTFOLIO = gql`
  mutation ClosePortfolio($portfolioId: UUID!, $reason: String) {
    closePortfolio(portfolioId: $portfolioId, reason: $reason)
  }
`
