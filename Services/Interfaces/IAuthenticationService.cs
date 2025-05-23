using System.Threading.Tasks;

namespace MyGameCatalog.Services.Interfaces
{
    public interface IAuthenticationService
    {
        bool IsAuthenticated { get; }
        Task<bool> LoginWithCredentialsAsync(string username, string password);
        void Logout();
    }
}
