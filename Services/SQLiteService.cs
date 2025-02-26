using System;
using System.IO;
using System.Threading.Tasks;
using MyGameCatalog.Models;
using MyGameCatalog.Services.Interfaces;
using SQLite;

namespace MyGameCatalog.Services
{
    public class SQLiteService : ISQLiteService
    {
        public SQLiteAsyncConnection Database { get; private set; }

        public async Task InitializeAsync(string dbPath = null)
        {
            if (Database != null)
                return;

            if (string.IsNullOrEmpty(dbPath))
            {
                var folderPath = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                dbPath = Path.Combine(folderPath, "GameCatalog.db3");
            }

            Database = new SQLiteAsyncConnection(dbPath);
            await Database.CreateTableAsync<User>();
            await Database.CreateTableAsync<Game>();
            await Database.CreateTableAsync<UserCollection>();
        }
    }
}
