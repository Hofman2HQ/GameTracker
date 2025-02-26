using System.Collections.Generic;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using MyGameCatalog.Models;
using MyGameCatalog.Services.Interfaces;

namespace MyGameCatalog.Services
{
    public class FirebaseService : IFirebaseService
    {
        private readonly HttpClient _httpClient;
        private readonly string _firebaseBaseUrl;

        public FirebaseService(string firebaseBaseUrl)
        {
            _firebaseBaseUrl = firebaseBaseUrl;
            _httpClient = new HttpClient();
        }

        public async Task<bool> UploadUserCollectionsAsync(int userId, List<UserCollection> collections)
        {
            var url = $"{_firebaseBaseUrl}/userCollections/{userId}.json";
            var json = JsonSerializer.Serialize(collections);
            var content = new StringContent(json, Encoding.UTF8, "application/json");
            var response = await _httpClient.PutAsync(url, content);
            return response.IsSuccessStatusCode;
        }

        public async Task<List<UserCollection>> DownloadUserCollectionsAsync(int userId)
        {
            var url = $"{_firebaseBaseUrl}/userCollections/{userId}.json";
            var response = await _httpClient.GetAsync(url);
            if (response.IsSuccessStatusCode)
            {
                var json = await response.Content.ReadAsStringAsync();
                var collections = JsonSerializer.Deserialize<List<UserCollection>>(json);
                return collections ?? new List<UserCollection>();
            }
            return new List<UserCollection>();
        }
    }
}