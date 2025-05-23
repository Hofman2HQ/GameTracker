using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Threading.Tasks;
using MyGameCatalog.Services.Interfaces;

namespace MyGameCatalog.Services
{
    public class ConfigurationService : IConfigurationService
    {
        private readonly string _configPath;
        private Dictionary<string, string> _settings;
        private readonly object _lock = new object();

        public ConfigurationService()
        {
            _configPath = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "settings.json");
            _settings = new Dictionary<string, string>();
        }

        public string GetValue(string key)
        {
            lock (_lock)
            {
                return _settings.TryGetValue(key, out var value) ? value : null;
            }
        }

        public T GetValue<T>(string key, T defaultValue = default)
        {
            var value = GetValue(key);
            if (string.IsNullOrEmpty(value))
                return defaultValue;

            try
            {
                return JsonSerializer.Deserialize<T>(value);
            }
            catch
            {
                return defaultValue;
            }
        }

        public void SetValue(string key, string value)
        {
            lock (_lock)
            {
                _settings[key] = value;
            }
        }

        public void SetValue<T>(string key, T value)
        {
            var jsonValue = JsonSerializer.Serialize(value);
            SetValue(key, jsonValue);
        }

        public async Task SaveAsync()
        {
            Dictionary<string, string> settingsCopy;
            lock (_lock)
            {
                settingsCopy = new Dictionary<string, string>(_settings);
            }

            var json = JsonSerializer.Serialize(settingsCopy);
            await File.WriteAllTextAsync(_configPath, json);
        }

        public async Task LoadAsync()
        {
            try
            {
                if (File.Exists(_configPath))
                {
                    var json = await File.ReadAllTextAsync(_configPath);
                    var settings = JsonSerializer.Deserialize<Dictionary<string, string>>(json);
                    
                    lock (_lock)
                    {
                        _settings = settings ?? new Dictionary<string, string>();
                    }
                }
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Failed to load settings: {ex.Message}");
                lock (_lock)
                {
                    _settings = new Dictionary<string, string>();
                }
            }
        }
    }
}
