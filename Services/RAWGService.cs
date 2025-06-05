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
        private const int MaxCacheSize = 100;
        private const int CacheExpirationSeconds = 60;
        private const int RequestTimeoutSeconds = 30;

        // In-memory cache: query string -> (timestamp, results)
        private readonly Dictionary<string, (DateTime timestamp, List<Game> results)> _cache = new();

        public RAWGService(string apiKey)
        {
            if (string.IsNullOrWhiteSpace(apiKey))
                throw new ArgumentException("API key cannot be null or empty", nameof(apiKey));

            _apiKey = apiKey;
            _httpClient = new HttpClient
            {
                Timeout = TimeSpan.FromSeconds(RequestTimeoutSeconds)
            };
        }

        public async Task<List<Game>> SearchGamesAsync(string query)
        {
            if (string.IsNullOrWhiteSpace(query))
                throw new ArgumentException("Search query cannot be null or empty", nameof(query));

            // Return cached results if query is less than CacheExpirationSeconds old
            if (_cache.TryGetValue(query, out var cacheEntry) &&
                (DateTime.UtcNow - cacheEntry.timestamp).TotalSeconds < CacheExpirationSeconds)
            {
                return cacheEntry.results;
            }

            try
            {
                var requestUrl = $"{BaseUrl}/games?key={_apiKey}&search={Uri.EscapeDataString(query)}";
                var response = await _httpClient.GetAsync(requestUrl);

                if (response.StatusCode == System.Net.HttpStatusCode.TooManyRequests)
                {
                    throw new ApplicationException("API rate limit exceeded. Please try again later.");
                }

                response.EnsureSuccessStatusCode();
                var json = await response.Content.ReadAsStringAsync();
                var games = new List<Game>();

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

                // Manage cache size
                if (_cache.Count >= MaxCacheSize)
                {
                    var oldestKey = _cache.OrderBy(x => x.Value.timestamp).First().Key;
                    _cache.Remove(oldestKey);
                }

                // Cache the search result
                _cache[query] = (DateTime.UtcNow, games);
                return games;
            }
            catch (HttpRequestException ex)
            {
                throw new ApplicationException("Failed to connect to RAWG API. Please check your internet connection.", ex);
            }
            catch (TaskCanceledException)
            {
                throw new ApplicationException("Request timed out. Please try again.");
            }
            catch (JsonException ex)
            {
                throw new ApplicationException("Failed to parse API response.", ex);
            }
        }

        public async Task<Game> GetGameDetailsAsync(int gameId)
        {
            try
            {
                var requestUrl = $"{BaseUrl}/games/{gameId}?key={_apiKey}";
                var response = await _httpClient.GetAsync(requestUrl);

                if (response.StatusCode == System.Net.HttpStatusCode.TooManyRequests)
                {
                    throw new ApplicationException("API rate limit exceeded. Please try again later.");
                }

                response.EnsureSuccessStatusCode();
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
            catch (HttpRequestException ex)
            {
                throw new ApplicationException("Failed to connect to RAWG API. Please check your internet connection.", ex);
            }
            catch (TaskCanceledException)
            {
                throw new ApplicationException("Request timed out. Please try again.");
            }
            catch (JsonException ex)
            {
                throw new ApplicationException("Failed to parse API response.", ex);
            }
        }
    }
}