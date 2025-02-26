using System.Collections.Generic;
using System.Threading.Tasks;
using MyGameCatalog.Models;

namespace MyGameCatalog.Services.Interfaces
{
    public interface IRAWGService
    {
        Task<List<Game>> SearchGamesAsync(string query);
        Task<Game> GetGameDetailsAsync(int gameId);
    }
}
