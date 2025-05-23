using System.Threading.Tasks;

namespace MyGameCatalog.Services.Interfaces
{
    public interface IConfigurationService
    {
        string GetValue(string key);
        void SetValue(string key, string value);
        T GetValue<T>(string key, T defaultValue = default);
        void SetValue<T>(string key, T value);
        Task SaveAsync();
        Task LoadAsync();
    }
}
