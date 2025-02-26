using System.Threading.Tasks;

namespace MyGameCatalog.Services.Interfaces
{
    public interface IAuthenticationService
    {
        Task<string> LoginWithGoogleAsync();
    }
}
