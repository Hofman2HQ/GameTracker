using System.Threading.Tasks;
using SQLite;

namespace MyGameCatalog.Services.Interfaces
{
    public interface ISQLiteService
    {
        SQLiteAsyncConnection Database { get; }
        Task InitializeAsync(string dbPath = null);
    }
}
