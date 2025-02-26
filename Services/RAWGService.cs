using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Text.Json;
using System.Threading.Tasks;
using MyGameCatalog.Models;
using MyGameCatalog.Services.Interfaces;

namespace MyGameCatalog.Services
{
    public class RAWGService : IRAWGService
    {
        private readonly HttpClient _httpClient;
        private const string BaseUrl = "https://api.rawg.io/api";
        private readonly string _apiKey;

        // In-memory cache: query string -> (timestamp, results)
        private readonly Dictionary<string, (DateTime timestamp, List<Game> results)> _cache = new();

        public RAWGService(string apiKey)
        {
            _apiKey = apiKey;
            _httpClient = new HttpClient();
        }

        public async Task<List<Game>> SearchGamesAsync(string query)
        {
            // Return cached results if query is less than 60 seconds old.
            if (_cache.TryGetValue(query, out var cacheEntry) &&
                (DateTime.UtcNow - cacheEntry.timestamp).TotalSeconds < 60)
            {
                return cacheEntry.results;
            }

            var requestUrl = $"{BaseUrl}/games?key={_apiKey}&search={Uri.EscapeDataString(query)}";
            var response = await _httpClient.GetAsync(requestUrl);
            var games = new List<Game>();

            if (response.IsSuccessStatusCode)
            {
                var json = await response.Content.ReadAsStringAsync();
                using var doc = JsonDocument.Parse(json);
                if (doc.RootElement.TryGetProperty("results", out JsonElement results))
                {
                    foreach (var item in results.EnumerateArray())
                    {
                        games.Add(new Game
                        {
                            GameId = item.GetProperty("id").GetInt32(),
                            Title = item.GetProperty("name").GetString(),
                            CoverArtUrl = item.GetProperty("background_image").GetString(),
                            Description = "" // Optionally get detailed info later.
                        });
                    }
                }
            }
            // Cache the search result.
            _cache[query] = (DateTime.UtcNow, games);
            return games;
        }

        public async Task<Game> GetGameDetailsAsync(int gameId)
        {
            var requestUrl = $"{BaseUrl}/games/{gameId}?key={_apiKey}";
            var response = await _httpClient.GetAsync(requestUrl);
            if (response.IsSuccessStatusCode)
            {
                var json = await response.Content.ReadAsStringAsync();
                using var doc = JsonDocument.Parse(json);
                var root = doc.RootElement;
                return new Game
                {
                    GameId = root.GetProperty("id").GetInt32(),
                    Title = root.GetProperty("name").GetString(),
                    CoverArtUrl = root.GetProperty("background_image").GetString(),
                    Description = root.GetProperty("description_raw").GetString()
                };
            }
            return null;
        }
    }
}