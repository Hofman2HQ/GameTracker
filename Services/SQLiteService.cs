using System;
using System.IO;
using System.Threading.Tasks;
using MyGameCatalog.Models;
using MyGameCatalog.Services.Interfaces;
using SQLite;

namespace MyGameCatalog.Services
{
    public class SQLiteService : ISQLiteService, IAsyncDisposable
    {
        public SQLiteAsyncConnection Database { get; private set; }
        private readonly string _dbPath;
        private bool _isInitialized;

        public SQLiteService()
        {
            _dbPath = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), 
                "GameCatalog.db3");
        }

        public async Task InitializeAsync(string dbPath = null)
        {
            if (_isInitialized)
                return;

            try
            {
                Database = new SQLiteAsyncConnection(dbPath ?? _dbPath);
                
                // Create tables if they don't exist
                await Database.CreateTablesAsync<CreateFlags.None,
                    User,
                    Game,
                    UserCollection>().ConfigureAwait(false);

                _isInitialized = true;
            }
            catch (SQLiteException ex)
            {
                System.Diagnostics.Debug.WriteLine($"Database initialization failed: {ex.Message}");
                throw new ApplicationException("Failed to initialize the database. Please ensure you have proper permissions.", ex);
            }
        }

        public async ValueTask DisposeAsync()
        {
            if (Database != null)
            {
                await Database.CloseAsync();
                Database = null;
            }
            _isInitialized = false;
        }

        private async Task EnsureInitializedAsync()
        {
            if (!_isInitialized)
            {
                await InitializeAsync();
            }
        }
    }
}
