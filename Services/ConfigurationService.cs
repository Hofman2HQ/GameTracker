using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Threading.Tasks;
using MyGameCatalog.Services.Interfaces;
using System.Collections.Concurrent;
using System.Threading.Tasks;
using System.Threading;

namespace MyGameCatalog.Services
{
    public interface IConfigurationService
    {
        Task LoadAsync();
        string GetValue(string key);
        void SetValue(string key, string value);
        Task SaveAsync();
    }

    public class ConfigurationService : IConfigurationService
    {
        private readonly ConcurrentDictionary<string, string> _config = new();
        private readonly string _configFile;
        private readonly SemaphoreSlim _semaphore = new(1, 1);

        public ConfigurationService()
        {
            _configFile = Path.Combine(FileSystem.AppDataDirectory, "config.json");
        }

        public async Task LoadAsync()
        {
            try
            {
                if (File.Exists(_configFile))
                {
                    var json = await File.ReadAllTextAsync(_configFile);
                    var config = System.Text.Json.JsonSerializer.Deserialize<Dictionary<string, string>>(json);
                    if (config != null)
                    {
                        foreach (var kvp in config)
                        {
                            _config[kvp.Key] = kvp.Value;
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Error loading configuration: {ex}");
            }
        }

        public string GetValue(string key)
        {
            return _config.TryGetValue(key, out var value) ? value : null;
        }

        public void SetValue(string key, string value)
        {
            if (value == null)
            {
                _config.TryRemove(key, out _);
            }
            else
            {
                _config[key] = value;
            }
        }

        public async Task SaveAsync()
        {
            try
            {
                await _semaphore.WaitAsync();
                var json = System.Text.Json.JsonSerializer.Serialize(_config);
                await File.WriteAllTextAsync(_configFile, json);
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Error saving configuration: {ex}");
            }
            finally
            {
                _semaphore.Release();
            }
        }
    }
}
