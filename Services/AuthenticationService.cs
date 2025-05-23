using System;
using System.Threading.Tasks;
using Microsoft.Maui.Authentication;
using Microsoft.Maui.Controls;
using MyGameCatalog.Services.Interfaces;

namespace MyGameCatalog.Services
{
    public class AuthenticationService : IAuthenticationService
    {
        private const string GoogleClientId = "YOUR_GOOGLE_CLIENT_ID";
        private const string GoogleRedirectUri = "YOUR_APP_SCHEME://oauth2redirect";
        private string _cachedEmail;
        private string _cachedUsername;
        private const string DEMO_USERNAME = "test";
        private const string DEMO_PASSWORD = "123";

        public bool IsAuthenticated => !string.IsNullOrEmpty(_cachedEmail) || !string.IsNullOrEmpty(_cachedUsername);

        public async Task<string> LoginWithGoogleAsync()
        {
            try
            {
                var authResult = await WebAuthenticator.AuthenticateAsync(
                    new WebAuthenticatorOptions
                    {
                        Url = new Uri($"https://accounts.google.com/o/oauth2/v2/auth" +
                            $"?client_id={GoogleClientId}" +
                            $"&redirect_uri={Uri.EscapeDataString(GoogleRedirectUri)}" +
                            "&response_type=token" +
                            "&scope=email profile"),
                        CallbackUrl = new Uri(GoogleRedirectUri)
                    });

                var accessToken = authResult?.AccessToken;
                if (string.IsNullOrEmpty(accessToken))
                    throw new ApplicationException("Authentication failed: No access token received");

                // Use the access token to get user info from Google
                using (var client = new System.Net.Http.HttpClient())
                {
                    client.DefaultRequestHeaders.Authorization = 
                        new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", accessToken);
                    
                    var userInfoResponse = await client.GetStringAsync(
                        "https://www.googleapis.com/oauth2/v2/userinfo");
                    
                    // Parse the JSON response to get email
                    var userInfo = System.Text.Json.JsonSerializer.Deserialize<GoogleUserInfo>(
                        userInfoResponse);
                    
                    _cachedEmail = userInfo.Email;
                    return _cachedEmail;
                }
            }
            catch (TaskCanceledException)
            {
                throw new ApplicationException("Authentication was cancelled by the user");
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Authentication error: {ex}");
                throw new ApplicationException("Authentication failed. Please try again.", ex);
            }
        }

        public async Task<bool> LoginWithCredentialsAsync(string username, string password)
        {
            // For demo purposes, we're using hardcoded credentials
            if (username == DEMO_USERNAME && password == DEMO_PASSWORD)
            {
                _cachedUsername = username;
                return true;
            }
            return false;
        }

        public void Logout()
        {
            _cachedEmail = null;
            _cachedUsername = null;
        }

        private class GoogleUserInfo
        {
            public string Email { get; set; }
            public string Name { get; set; }
            public string Picture { get; set; }
        }
    }
}