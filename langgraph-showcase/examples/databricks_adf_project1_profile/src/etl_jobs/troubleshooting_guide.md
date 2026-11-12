# Azure Authentication Troubleshooting Guide

This guide helps resolve authentication issues when accessing Azure Key Vault from Python applications.

## Common Error: DefaultAzureCredential Failed

The error you encountered indicates that none of the available authentication methods are working. Here are the solutions:

## Solution 1: Use Azure CLI Authentication (Recommended for Development)

1. Install Azure CLI:
   ```bash
   # Windows
   winget install Microsoft.AzureCLI
   
   # macOS
   brew install azure-cli
   
   # Linux
   curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
   ```

2. Login to Azure:
   ```bash
   az login
   ```

3. Set your subscription:
   ```bash
   az account set --subscription "your-subscription-id"
   ```

4. Test authentication:
   ```bash
   az account show
   ```

## Solution 2: Use Environment Variables (Service Principal)

1. Create a service principal:
   ```bash
   az ad sp create-for-rbac --name "my-app" --role contributor
   ```

2. Set environment variables:
   ```bash
   export AZURE_TENANT_ID="your-tenant-id"
   export AZURE_CLIENT_ID="your-client-id"
   export AZURE_CLIENT_SECRET="your-client-secret"
   ```

3. Grant Key Vault access:
   ```bash
   az keyvault set-policy --name "omvmcnp1kvtradinge2edev" \
     --spn "your-client-id" \
     --secret-permissions get list
   ```

## Solution 3: Use Managed Identity (Production)

1. Enable managed identity on your resource:
   ```bash
   # For VM
   az vm identity assign --name "your-vm" --resource-group "your-rg"
   
   # For App Service
   az webapp identity assign --name "your-app" --resource-group "your-rg"
   ```

2. Grant Key Vault access to managed identity:
   ```bash
   az keyvault set-policy --name "omvmcnp1kvtradinge2edev" \
     --object-id "managed-identity-object-id" \
     --secret-permissions get list
   ```

## Solution 4: Use Azure Developer CLI

1. Install Azure Developer CLI:
   ```bash
   # Windows
   winget install Microsoft.Azure.DevCLI
   
   # macOS
   brew install azure-dev
   
   # Linux
   curl -fsSL https://aka.ms/install-azd.sh | bash
   ```

2. Login:
   ```bash
   azd auth login
   ```

## Testing Your Authentication

Use the provided `azure_auth_config.py` to test your setup:

```python
from azure_auth_config import print_auth_status
print_auth_status()
```

## Environment-Specific Solutions

### Databricks Environment

If you're running in Databricks:

1. Use cluster-scoped init script:
   ```bash
   #!/bin/bash
   export AZURE_CLIENT_ID="your-managed-identity-client-id"
   ```

2. Or use notebook-scoped authentication:
   ```python
   from azure.identity import ManagedIdentityCredential
   credential = ManagedIdentityCredential(client_id="your-client-id")
   ```

### Local Development

1. Use Azure CLI (easiest):
   ```bash
   az login
   ```

2. Or use Visual Studio Code Azure extension

### CI/CD Pipeline

1. Use service principal with environment variables
2. Store secrets in pipeline variables
3. Use managed identity for Azure-hosted agents

## Key Vault Access Policies

Ensure your identity has the correct permissions:

```bash
# Check current policies
az keyvault show --name "omvmcnp1kvtradinge2edev" --query "properties.accessPolicies"

# Add policy for your identity
az keyvault set-policy --name "omvmcnp1kvtradinge2edev" \
  --object-id "your-object-id" \
  --secret-permissions get list
```

## Common Issues and Fixes

### Issue: "No accounts were found in the cache"
**Fix**: Run `az login` to authenticate with Azure CLI

### Issue: "Environment variables are not fully configured"
**Fix**: Set all required environment variables (AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET)

### Issue: "No response from the IMDS endpoint"
**Fix**: Ensure you're running on an Azure resource with managed identity enabled

### Issue: "Azure CLI not found on path"
**Fix**: Install Azure CLI or use a different authentication method

## Best Practices

1. **Development**: Use Azure CLI authentication
2. **Testing**: Use service principal with environment variables
3. **Production**: Use managed identity
4. **Security**: Never commit secrets to source control
5. **Monitoring**: Use Application Insights for authentication monitoring

## Verification Steps

After implementing any solution:

1. Test authentication:
   ```python
   from azure.identity import DefaultAzureCredential
   credential = DefaultAzureCredential()
   token = credential.get_token("https://vault.azure.net/.default")
   print("Authentication successful!")
   ```

2. Test Key Vault access:
   ```python
   from azure.keyvault.secrets import SecretClient
   client = SecretClient(vault_url="https://your-vault.vault.azure.net/", credential=credential)
   secret = client.get_secret("test-secret")
   print("Key Vault access successful!")
   ```

## Support

If you continue to have issues:

1. Check Azure status page
2. Review Azure Key Vault documentation
3. Check Azure Identity library documentation
4. Contact Azure support if needed 