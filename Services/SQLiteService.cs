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
        private const int CurrentDbVersion = 1;
        private const string VersionKey = "db_version";

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

                // Check and handle database version
                await HandleDatabaseVersionAsync();

                _isInitialized = true;
            }
            catch (SQLiteException ex)
            {
                System.Diagnostics.Debug.WriteLine($"Database initialization failed: {ex.Message}");
                throw new ApplicationException("Failed to initialize the database. Please ensure you have proper permissions.", ex);
            }
        }

        private async Task HandleDatabaseVersionAsync()
        {
            try
            {
                var version = await GetDatabaseVersionAsync();
                if (version < CurrentDbVersion)
                {
                    await Database.RunInTransactionAsync(conn =>
                    {
                        // Perform database migrations here
                        if (version < 1)
                        {
                            // Example migration: Add new column
                            conn.Execute("ALTER TABLE User ADD COLUMN LastLoginDate TEXT");
                        }
                    });

                    await SetDatabaseVersionAsync(CurrentDbVersion);
                }
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Database version check failed: {ex.Message}");
                throw;
            }
        }

        private async Task<int> GetDatabaseVersionAsync()
        {
            try
            {
                var result = await Database.ExecuteScalarAsync<int>(
                    "SELECT value FROM AppSettings WHERE key = ?", VersionKey);
                return result;
            }
            catch
            {
                return 0;
            }
        }

        private async Task SetDatabaseVersionAsync(int version)
        {
            await Database.ExecuteAsync(
                "INSERT OR REPLACE INTO AppSettings (key, value) VALUES (?, ?)",
                VersionKey, version);
        }

        public async Task BackupDatabaseAsync()
        {
            if (!_isInitialized)
                throw new InvalidOperationException("Database not initialized");

            var backupPath = _dbPath + ".backup";
            try
            {
                await Database.CloseAsync();
                File.Copy(_dbPath, backupPath, true);
                Database = new SQLiteAsyncConnection(_dbPath);
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Database backup failed: {ex.Message}");
                throw new ApplicationException("Failed to backup database", ex);
            }
        }

        public async Task RestoreFromBackupAsync()
        {
            var backupPath = _dbPath + ".backup";
            if (!File.Exists(backupPath))
                throw new FileNotFoundException("Backup file not found");

            try
            {
                await Database.CloseAsync();
                File.Copy(backupPath, _dbPath, true);
                Database = new SQLiteAsyncConnection(_dbPath);
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Database restore failed: {ex.Message}");
                throw new ApplicationException("Failed to restore database from backup", ex);
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
