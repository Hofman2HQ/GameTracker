using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using MyGameCatalog.Models;
using MyGameCatalog.Services.Interfaces;
using System.Net;

namespace MyGameCatalog.Services
{
    public class FirebaseService : IFirebaseService, IDisposable
    {
        private readonly HttpClient _httpClient;
        private readonly string _firebaseBaseUrl;
        private readonly int _maxRetries = 3;
        private readonly TimeSpan _timeout = TimeSpan.FromSeconds(30);

        public FirebaseService(string firebaseBaseUrl)
        {
            if (string.IsNullOrEmpty(firebaseBaseUrl))
                throw new ArgumentNullException(nameof(firebaseBaseUrl));

            _firebaseBaseUrl = firebaseBaseUrl;
            _httpClient = new HttpClient { Timeout = _timeout };
        }

        public async Task<bool> UploadUserCollectionsAsync(int userId, List<UserCollection> collections)
        {
            if (userId <= 0)
                throw new ArgumentException("Invalid user ID", nameof(userId));
            if (collections == null)
                throw new ArgumentNullException(nameof(collections));

            var retryCount = 0;
            while (retryCount < _maxRetries)
            {
                try
                {
                    var url = $"{_firebaseBaseUrl}/userCollections/{userId}.json";
                    var json = JsonSerializer.Serialize(collections);
                    var content = new StringContent(json, Encoding.UTF8, "application/json");
                    
                    var response = await _httpClient.PutAsync(url, content);
                    response.EnsureSuccessStatusCode();
                    return true;
                }
                catch (HttpRequestException ex)
                {
                    retryCount++;
                    if (retryCount >= _maxRetries)
                        throw new ApplicationException($"Failed to upload collections after {_maxRetries} attempts", ex);
                    
                    await Task.Delay(1000 * retryCount); // Exponential backoff
                }
            }
            return false;
        }

        public async Task<List<UserCollection>> DownloadUserCollectionsAsync(int userId)
        {
            if (userId <= 0)
                throw new ArgumentException("Invalid user ID", nameof(userId));

            var retryCount = 0;
            while (retryCount < _maxRetries)
            {
                try
                {
                    var url = $"{_firebaseBaseUrl}/userCollections/{userId}.json";
                    var response = await _httpClient.GetAsync(url);
                    
                    if (response.StatusCode == HttpStatusCode.NotFound)
                        return new List<UserCollection>();

                    response.EnsureSuccessStatusCode();
                    var json = await response.Content.ReadAsStringAsync();
                    
                    if (string.IsNullOrEmpty(json) || json == "null")
                        return new List<UserCollection>();

                    var collections = JsonSerializer.Deserialize<List<UserCollection>>(json);
                    return collections ?? new List<UserCollection>();
                }
                catch (HttpRequestException ex)
                {
                    retryCount++;
                    if (retryCount >= _maxRetries)
                        throw new ApplicationException($"Failed to download collections after {_maxRetries} attempts", ex);
                    
                    await Task.Delay(1000 * retryCount); // Exponential backoff
                }
            }
            return new List<UserCollection>();
        }

        public void Dispose()
        {
            _httpClient?.Dispose();
        }
    }
}