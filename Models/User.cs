using SQLite;

namespace MyGameCatalog.Models
{
    public class User
    {
        [PrimaryKey, AutoIncrement]
        public int Id { get; set; }
        
        [Unique]
        public string Email { get; set; }
    }
}