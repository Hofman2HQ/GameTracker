using System;
using System.Threading.Tasks;
using Microsoft.Maui.Authentication;
using Microsoft.Maui.Controls;
using MyGameCatalog.Services.Interfaces;
using System.Net.Http;
using System.Text.Json;
using System.Security.Cryptography;
using System.Text;

namespace MyGameCatalog.Services
{
    public class AuthenticationService : IAuthenticationService
    {
        private readonly IConfigurationService _configService;
        private readonly ISecureStorage _secureStorage;
        private string _cachedEmail;
        private string _cachedUsername;
        private string _refreshToken;
        private DateTime _tokenExpiration;
        private const string DEMO_USERNAME = "test";
        private const string DEMO_PASSWORD = "123";
        private const string TOKEN_KEY = "auth_token";
        private const string REFRESH_TOKEN_KEY = "refresh_token";
        private const string TOKEN_EXPIRATION_KEY = "token_expiration";

        public AuthenticationService(IConfigurationService configService, ISecureStorage secureStorage)
        {
            _configService = configService ?? throw new ArgumentNullException(nameof(configService));
            _secureStorage = secureStorage ?? throw new ArgumentNullException(nameof(secureStorage));
        }

        public bool IsAuthenticated => !string.IsNullOrEmpty(_cachedEmail) || !string.IsNullOrEmpty(_cachedUsername);

        public async Task<string> LoginWithGoogleAsync()
        {
            try
            {
                var clientId = await _configService.GetValueAsync("GoogleClientId");
                var redirectUri = await _configService.GetValueAsync("GoogleRedirectUri");

                if (string.IsNullOrEmpty(clientId) || string.IsNullOrEmpty(redirectUri))
                {
                    throw new ApplicationException("Google authentication configuration is missing");
                }

                var authResult = await WebAuthenticator.AuthenticateAsync(
                    new WebAuthenticatorOptions
                    {
                        Url = new Uri($"https://accounts.google.com/o/oauth2/v2/auth" +
                            $"?client_id={clientId}" +
                            $"&redirect_uri={Uri.EscapeDataString(redirectUri)}" +
                            "&response_type=token" +
                            "&scope=email profile"),
                        CallbackUrl = new Uri(redirectUri)
                    });

                var accessToken = authResult?.AccessToken;
                if (string.IsNullOrEmpty(accessToken))
                    throw new ApplicationException("Authentication failed: No access token received");

                // Store tokens securely
                await _secureStorage.SetAsync(TOKEN_KEY, accessToken);
                if (authResult.Properties.TryGetValue("refresh_token", out var refreshToken))
                {
                    await _secureStorage.SetAsync(REFRESH_TOKEN_KEY, refreshToken);
                    _refreshToken = refreshToken;
                }

                // Set token expiration
                _tokenExpiration = DateTime.UtcNow.AddHours(1);
                await _secureStorage.SetAsync(TOKEN_EXPIRATION_KEY, _tokenExpiration.ToString("O"));

                // Get user info
                using (var client = new HttpClient())
                {
                    client.DefaultRequestHeaders.Authorization = 
                        new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", accessToken);
                    
                    var userInfoResponse = await client.GetStringAsync(
                        "https://www.googleapis.com/oauth2/v2/userinfo");
                    
                    var userInfo = JsonSerializer.Deserialize<GoogleUserInfo>(userInfoResponse);
                    _cachedEmail = userInfo.Email;
                    return _cachedEmail;
                }
            }
            catch (TaskCanceledException)
            {
                throw new ApplicationException("Authentication was cancelled by the user");
            }
            catch (HttpRequestException ex)
            {
                throw new ApplicationException("Network error during authentication. Please check your internet connection.", ex);
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Authentication error: {ex}");
                throw new ApplicationException("Authentication failed. Please try again.", ex);
            }
        }

        public async Task<bool> LoginWithCredentialsAsync(string username, string password)
        {
            if (string.IsNullOrEmpty(username) || string.IsNullOrEmpty(password))
                throw new ArgumentException("Username and password cannot be empty");

            try
            {
                // For demo purposes, we're using hardcoded credentials
                if (username == DEMO_USERNAME && password == DEMO_PASSWORD)
                {
                    _cachedUsername = username;
                    // Store a secure hash of the credentials
                    var hashedPassword = HashPassword(password);
                    await _secureStorage.SetAsync("demo_credentials", hashedPassword);
                    return true;
                }
                return false;
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Login error: {ex}");
                throw new ApplicationException("Login failed. Please try again.", ex);
            }
        }

        public async Task RefreshTokenAsync()
        {
            if (string.IsNullOrEmpty(_refreshToken))
                throw new InvalidOperationException("No refresh token available");

            try
            {
                var clientId = await _configService.GetValueAsync("GoogleClientId");
                var clientSecret = await _configService.GetValueAsync("GoogleClientSecret");

                using (var client = new HttpClient())
                {
                    var content = new FormUrlEncodedContent(new[]
                    {
                        new KeyValuePair<string, string>("client_id", clientId),
                        new KeyValuePair<string, string>("client_secret", clientSecret),
                        new KeyValuePair<string, string>("refresh_token", _refreshToken),
                        new KeyValuePair<string, string>("grant_type", "refresh_token")
                    });

                    var response = await client.PostAsync("https://oauth2.googleapis.com/token", content);
                    response.EnsureSuccessStatusCode();

                    var json = await response.Content.ReadAsStringAsync();
                    var tokenResponse = JsonSerializer.Deserialize<TokenResponse>(json);

                    await _secureStorage.SetAsync(TOKEN_KEY, tokenResponse.AccessToken);
                    _tokenExpiration = DateTime.UtcNow.AddSeconds(tokenResponse.ExpiresIn);
                    await _secureStorage.SetAsync(TOKEN_EXPIRATION_KEY, _tokenExpiration.ToString("O"));
                }
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Token refresh failed: {ex}");
                throw new ApplicationException("Failed to refresh authentication token", ex);
            }
        }

        public async Task Logout()
        {
            try
            {
                _cachedEmail = null;
                _cachedUsername = null;
                _refreshToken = null;
                await _secureStorage.SetAsync(TOKEN_KEY, null);
                await _secureStorage.SetAsync(REFRESH_TOKEN_KEY, null);
                await _secureStorage.SetAsync(TOKEN_EXPIRATION_KEY, null);
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Logout error: {ex}");
                throw new ApplicationException("Failed to logout properly", ex);
            }
        }

        private string HashPassword(string password)
        {
            using (var sha256 = SHA256.Create())
            {
                var hashedBytes = sha256.ComputeHash(Encoding.UTF8.GetBytes(password));
                return Convert.ToBase64String(hashedBytes);
            }
        }

        private class GoogleUserInfo
        {
            public string Email { get; set; }
            public string Name { get; set; }
            public string Picture { get; set; }
        }

        private class TokenResponse
        {
            public string AccessToken { get; set; }
            public int ExpiresIn { get; set; }
            public string RefreshToken { get; set; }
        }
    }
}