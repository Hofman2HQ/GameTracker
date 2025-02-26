using System.Collections.Generic;
using System.Threading.Tasks;
using MyGameCatalog.Models;

namespace MyGameCatalog.Services.Interfaces
{
    public interface IFirebaseService
    {
        Task<bool> UploadUserCollectionsAsync(int userId, List<UserCollection> collections);
        Task<List<UserCollection>> DownloadUserCollectionsAsync(int userId);
    }
}
